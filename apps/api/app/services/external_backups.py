from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.disk_handoff import handoff_disk_to_pbs
from app.services.external_backup_agent import AgentCommandError
from app.services.external_backup_agent import get_external_backup_agent_bridge
from app.services.external_backup_execution import build_export_target_path, get_external_backup_execution_service
from app.services.notifications import notify_backup_failure, notify_backup_success


@dataclass(frozen=True)
class ExternalBackupPlan:
    target_path: str
    mode: ExternalBackupMode
    preserves_existing_data: bool


def _expected_pbs_mount_path(serial_number: str) -> PurePosixPath:
    return PurePosixPath("/mnt/pbo") / serial_number


def build_external_backup_plan(disk: ExternalDisk) -> ExternalBackupPlan:
    base_path = _expected_pbs_mount_path(disk.serial_number)
    settings = get_settings()

    if disk.dedicated_backup_disk or not settings.external_backup_legacy_coexistence_enabled:
        return ExternalBackupPlan(
            target_path=build_export_target_path(str(base_path), disk.serial_number, ExternalBackupMode.DEDICATED),
            mode=ExternalBackupMode.DEDICATED,
            preserves_existing_data=False,
        )

    if settings.external_backup_legacy_coexistence_enabled and disk.allow_existing_data:
        return ExternalBackupPlan(
            target_path=build_export_target_path(str(base_path), disk.serial_number, ExternalBackupMode.COEXISTENCE),
            mode=ExternalBackupMode.COEXISTENCE,
            preserves_existing_data=True,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Disk must be dedicated before an external backup can run.",
    )


def _get_disk_or_404(db: Session, disk_id: int) -> ExternalDisk:
    disk = db.get(ExternalDisk, disk_id)
    if disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")
    return disk


def get_external_backup_preview(db: Session, disk_id: int) -> dict[str, str | bool | int | None]:
    disk = _get_disk_or_404(db, disk_id)
    plan = build_external_backup_plan(disk)
    settings = get_settings()
    estimated_needed_gb = disk.usable_capacity_gb or disk.capacity_gb
    loop_size_gb = settings.external_loop_datastore_size_gb if plan.mode == ExternalBackupMode.COEXISTENCE else None
    return {
        "target_path": plan.target_path,
        "mode": plan.mode.value,
        "preserves_existing_data": plan.preserves_existing_data,
        "loop_image_size_gb": loop_size_gb,
        "loop_image_size_warning": bool(loop_size_gb is not None and estimated_needed_gb and loop_size_gb < estimated_needed_gb),
    }


def list_external_backup_runs(db: Session) -> list[ExternalBackupRun]:
    return list(
        db.scalars(select(ExternalBackupRun).order_by(ExternalBackupRun.started_at.desc()))
    )


def get_external_backup_run(db: Session, run_id: int) -> ExternalBackupRun:
    run = db.get(ExternalBackupRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External backup run not found")
    return run


def delete_external_backup_run(db: Session, run_id: int) -> None:
    run = get_external_backup_run(db, run_id)
    if run.status in {BackupRunStatus.PENDING, BackupRunStatus.RUNNING}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending or running external backup runs cannot be deleted.",
        )

    db.delete(run)
    db.commit()


def cleanup_external_backup_runs(db: Session, keep_last: int = 10) -> int:
    keep_last = max(0, keep_last)
    runs = list_external_backup_runs(db)
    protected_ids = {
        run.id
        for run in runs[:keep_last]
    } | {
        run.id
        for run in runs
        if run.status in {BackupRunStatus.PENDING, BackupRunStatus.RUNNING}
    }
    deletable = [
        run
        for run in runs
        if run.status == BackupRunStatus.FAILED and run.id not in protected_ids
    ]

    for run in deletable:
        db.delete(run)
    db.commit()
    return len(deletable)


def cleanup_legacy_external_export_objects() -> dict[str, object]:
    result = get_external_backup_agent_bridge().cleanup_legacy_external_export_objects()
    return {
        "ok": result.ok,
        "message": result.message,
        "return_code": result.return_code,
    }


def run_external_backup(
    db: Session,
    disk_id: int,
    confirmation: bool,
    datastore_name: str | None = None,
) -> ExternalBackupRun:
    if not confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="External backup execution requires explicit confirmation.",
        )

    disk = _get_disk_or_404(db, disk_id)
    if not disk.trusted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only trusted disks can be used for external backups.",
        )

    if not disk.connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disk must be connected before an external backup can run.",
        )

    plan = build_external_backup_plan(disk)
    settings = get_settings()
    now = datetime.utcnow()
    run = ExternalBackupRun(
        disk_id=disk.id,
        status=BackupRunStatus.PENDING,
        started_at=now,
        finished_at=None,
        target_path=plan.target_path,
        datastore_name=datastore_name or settings.pbs_datastore,
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=None,
        current_step="starting",
        progress_message="External backup run queued.",
        last_log_at=now,
        mode=plan.mode,
        created_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    append_external_backup_run_log(
        db,
        run.id,
        step="starting",
        message="External backup run created. Background execution will start shortly.",
    )
    db.refresh(run)
    return run


def execute_external_backup_run(run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(ExternalBackupRun, run_id)
        if run is None:
            return
        disk = db.get(ExternalDisk, run.disk_id)
        if disk is None:
            append_external_backup_run_log(
                db,
                run_id,
                step="failure",
                message="Disk no longer exists.",
                stream="stderr",
                line="Disk no longer exists.",
            )
            _finish_run(db, run, BackupRunStatus.FAILED, "Disk no longer exists.", return_code=None)
            notify_backup_failure(f"Disk {run.disk_id}", "failure", "Disk no longer exists.")
            return

        execution_service = get_external_backup_execution_service()

        run.status = BackupRunStatus.RUNNING
        run.current_step = "starting"
        run.progress_message = "Starting external backup execution."
        db.add(run)
        db.commit()
        db.refresh(run)
        append_external_backup_run_log(db, run.id, step="starting", message="Starting external backup execution.")

        prepare_result = None
        export_result = None
        try:
            append_external_backup_run_log(
                db,
                run.id,
                step="handoff_disk",
                message="Handing off USB disk to PBS VM.",
            )
            handoff_status = handoff_disk_to_pbs(
                db,
                disk,
                confirmation=True,
                progress=lambda step, message, line=None: append_external_backup_run_log(
                    db,
                    run.id,
                    step=step,
                    message=message,
                    line=line,
                ),
            )
            append_external_backup_run_log(
                db,
                run.id,
                step="handoff_disk",
                message=handoff_status.message,
            )
            execution_result = execution_service.execute(
                disk=disk,
                datastore_name=run.datastore_name,
                mode=run.mode,
                run_id=run.id,
                progress=lambda step, message, line=None: append_external_backup_run_log(
                    db,
                    run.id,
                    step=step,
                    message=message,
                    line=line,
                ),
            )
            prepare_result = execution_result.prepare
            export_result = execution_result.export
            run.target_path = execution_result.target_path
            if execution_result.target_datastore_name:
                disk.pbs_datastore_name = execution_result.target_datastore_name
                disk.pbs_mount_path = execution_result.target_path
                disk.pbs_filesystem_type = "ext4"
                disk.prepared_as_pbs_datastore = True
                db.add(disk)

            run.status = BackupRunStatus.SUCCESS
            run.finished_at = datetime.utcnow()
            run.message = f"{handoff_status.message} {export_result.message}".strip()
            run.stdout_log = _merge_logs(
                run.stdout_log,
                handoff_status.message,
                prepare_result.stdout_log,
                export_result.stdout_log,
            )
            run.stderr_log = _merge_logs(run.stderr_log, prepare_result.stderr_log, export_result.stderr_log)
            run.command_summary = _merge_logs(prepare_result.command_summary, export_result.command_summary)
            run.execution_cwd = _merge_logs(prepare_result.execution_cwd, export_result.execution_cwd)
            run.return_code = export_result.return_code
            run.current_step = "success"
            run.progress_message = run.message
            run.last_log_at = datetime.utcnow()
            append_external_backup_run_log(db, run.id, step="success", message=run.message)
        except AgentCommandError as exc:
            run.status = BackupRunStatus.FAILED
            run.finished_at = datetime.utcnow()
            run.message = str(exc)
            run.stdout_log = _merge_logs(
                run.stdout_log,
                prepare_result.stdout_log if prepare_result else None,
                exc.stdout_log,
            )
            run.stderr_log = _merge_logs(
                run.stderr_log,
                prepare_result.stderr_log if prepare_result else None,
                exc.stderr_log,
                str(exc),
            )
            run.command_summary = _merge_logs(
                prepare_result.command_summary if prepare_result else None,
                exc.command_summary,
            )
            run.execution_cwd = _merge_logs(
                prepare_result.execution_cwd if prepare_result else None,
                exc.execution_cwd,
            )
            run.return_code = exc.return_code
            run.current_step = "failure"
            run.progress_message = str(exc)
            run.last_log_at = datetime.utcnow()
            append_external_backup_run_log(db, run.id, step="failure", message=str(exc), stream="stderr", line=str(exc))
        except HTTPException as exc:
            run.status = BackupRunStatus.FAILED
            run.finished_at = datetime.utcnow()
            run.message = str(exc.detail)
            run.stderr_log = _merge_logs(run.stderr_log, str(exc.detail))
            run.return_code = None
            run.current_step = "failure"
            run.progress_message = str(exc.detail)
            run.last_log_at = datetime.utcnow()
            append_external_backup_run_log(db, run.id, step="failure", message=str(exc.detail), stream="stderr", line=str(exc.detail))
        except RuntimeError as exc:
            run.status = BackupRunStatus.FAILED
            run.finished_at = datetime.utcnow()
            run.message = str(exc)
            run.stdout_log = _merge_logs(
                run.stdout_log,
                prepare_result.stdout_log if prepare_result else None,
                export_result.stdout_log if export_result else None,
            )
            run.stderr_log = _merge_logs(
                run.stderr_log,
                prepare_result.stderr_log if prepare_result else None,
                export_result.stderr_log if export_result else None,
                str(exc),
            )
            run.command_summary = _merge_logs(
                prepare_result.command_summary if prepare_result else None,
                export_result.command_summary if export_result else None,
            )
            run.execution_cwd = _merge_logs(
                prepare_result.execution_cwd if prepare_result else None,
                export_result.execution_cwd if export_result else None,
            )
            run.return_code = export_result.return_code if export_result else prepare_result.return_code if prepare_result else None
            run.current_step = "failure"
            run.progress_message = str(exc)
            run.last_log_at = datetime.utcnow()
            append_external_backup_run_log(db, run.id, step="failure", message=str(exc), stream="stderr", line=str(exc))
        except Exception as exc:
            run.status = BackupRunStatus.FAILED
            run.finished_at = datetime.utcnow()
            run.message = str(exc)
            run.stderr_log = _merge_logs(run.stderr_log, str(exc))
            run.return_code = None
            run.current_step = "failure"
            run.progress_message = str(exc)
            run.last_log_at = datetime.utcnow()
            append_external_backup_run_log(db, run.id, step="failure", message=str(exc), stream="stderr", line=str(exc))

        db.add(run)
        db.commit()
        disk_label = _format_disk_notification_label(disk, run.datastore_name)
        if run.status == BackupRunStatus.SUCCESS:
            notify_backup_success(disk_label)
        elif run.status == BackupRunStatus.FAILED:
            notify_backup_failure(disk_label, run.current_step, run.message)


def append_external_backup_run_log(
    db: Session,
    run_id: int,
    *,
    step: str | None,
    message: str | None,
    stream: Literal["stdout", "stderr"] = "stdout",
    line: str | None = None,
    command: str | None = None,
) -> ExternalBackupRun:
    run = get_external_backup_run(db, run_id)
    now = datetime.utcnow()
    clean_step = (step or run.current_step or "progress").strip()[:128]
    clean_message = (message or line or command or "Progress update.").strip()
    entry_parts = [f"[{now.isoformat(timespec='seconds')}Z]", clean_step]
    if command:
        entry_parts.append(f"command={command}")
    if clean_message:
        entry_parts.append(clean_message)
    if line and line != clean_message:
        entry_parts.append(line.rstrip())
    entry = " ".join(entry_parts)

    if stream == "stderr":
        run.stderr_log = _append_log(run.stderr_log, entry)
    else:
        run.stdout_log = _append_log(run.stdout_log, entry)
    run.current_step = clean_step
    run.progress_message = clean_message
    run.last_log_at = now
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_run(
    db: Session,
    run: ExternalBackupRun,
    status_value: BackupRunStatus,
    message: str,
    *,
    return_code: int | None,
) -> None:
    run.status = status_value
    run.finished_at = datetime.utcnow()
    run.message = message
    run.progress_message = message
    run.return_code = return_code
    run.last_log_at = datetime.utcnow()
    db.add(run)
    db.commit()


def _format_disk_notification_label(disk: ExternalDisk, datastore_name: str | None = None) -> str:
    label = disk.display_name or disk.serial_number
    details = [f"serial {disk.serial_number}"]
    if disk.model_name:
        details.append(f"model {disk.model_name}")
    if datastore_name:
        details.append(f"datastore {datastore_name}")
    if disk.source:
        details.append(f"source {disk.source}")
    return f"{label} ({', '.join(details)})"


def _merge_logs(*values: str | None) -> str | None:
    merged = "\n\n".join(value for value in values if value)
    return merged or None


def _append_log(existing: str | None, entry: str) -> str:
    if not existing:
        return entry
    return f"{existing}\n{entry}"
