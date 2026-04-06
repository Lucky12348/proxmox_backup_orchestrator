from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.external_backup_agent import AgentCommandError, get_external_backup_agent_bridge


@dataclass(frozen=True)
class ExternalBackupPlan:
    target_path: str
    mode: ExternalBackupMode
    preserves_existing_data: bool


def _require_mount_path(disk: ExternalDisk) -> PurePosixPath:
    if disk.mount_path:
        return PurePosixPath(disk.mount_path)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Disk has no mount path for external backup execution.",
    )


def _normalize_base_path(disk: ExternalDisk) -> PurePosixPath:
    mount_path = _require_mount_path(disk)
    base_path = PurePosixPath(disk.preferred_root_path) if disk.preferred_root_path else mount_path

    try:
        base_path.relative_to(mount_path)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preferred root path must stay inside the disk mount path.",
        ) from exc

    return base_path


def build_external_backup_plan(disk: ExternalDisk) -> ExternalBackupPlan:
    base_path = _normalize_base_path(disk)

    if disk.dedicated_backup_disk:
        target = base_path / "pbs-datastore"
        return ExternalBackupPlan(
            target_path=str(target),
            mode=ExternalBackupMode.DEDICATED,
            preserves_existing_data=False,
        )

    if disk.allow_existing_data:
        target = (
            base_path
            / "proxmox-backup-orchestrator"
            / disk.serial_number
            / "pbs-datastore"
        )
        return ExternalBackupPlan(
            target_path=str(target),
            mode=ExternalBackupMode.COEXISTENCE,
            preserves_existing_data=True,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Disk must be dedicated or allow existing data before an external backup can run.",
    )


def _get_disk_or_404(db: Session, disk_id: int) -> ExternalDisk:
    disk = db.get(ExternalDisk, disk_id)
    if disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")
    return disk


def get_external_backup_preview(db: Session, disk_id: int) -> dict[str, str | bool]:
    disk = _get_disk_or_404(db, disk_id)
    plan = build_external_backup_plan(disk)
    return {
        "target_path": plan.target_path,
        "mode": plan.mode.value,
        "preserves_existing_data": plan.preserves_existing_data,
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


def run_external_backup(db: Session, disk_id: int, confirmation: bool) -> ExternalBackupRun:
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

    if not disk.mount_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disk must have a mount path before an external backup can run.",
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
        datastore_name=settings.pbs_datastore,
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        mode=plan.mode,
        created_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    bridge = get_external_backup_agent_bridge()

    run.status = BackupRunStatus.RUNNING
    db.add(run)
    db.commit()
    db.refresh(run)

    prepare_result = None
    export_result = None
    try:
        prepare_result = bridge.prepare_external_datastore(disk, plan.target_path, plan.mode)
        if not prepare_result.ok:
            raise RuntimeError(prepare_result.message)

        export_result = bridge.run_external_export(plan.target_path, settings.pbs_datastore, plan.mode)
        if not export_result.ok:
            raise RuntimeError(export_result.message)

        run.status = BackupRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        run.message = export_result.message
        run.stdout_log = _merge_logs(prepare_result.stdout_log, export_result.stdout_log)
        run.stderr_log = _merge_logs(prepare_result.stderr_log, export_result.stderr_log)
        run.command_summary = _merge_logs(prepare_result.command_summary, export_result.command_summary)
    except AgentCommandError as exc:
        run.status = BackupRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.message = str(exc)
        run.stdout_log = _merge_logs(
            prepare_result.stdout_log if prepare_result else None,
            exc.stdout_log,
        )
        run.stderr_log = _merge_logs(
            prepare_result.stderr_log if prepare_result else None,
            exc.stderr_log,
            str(exc),
        )
        run.command_summary = _merge_logs(
            prepare_result.command_summary if prepare_result else None,
            exc.command_summary,
        )
    except RuntimeError as exc:
        run.status = BackupRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.message = str(exc)
        run.stdout_log = _merge_logs(
            prepare_result.stdout_log if prepare_result else None,
            export_result.stdout_log if export_result else None,
        )
        run.stderr_log = _merge_logs(
            prepare_result.stderr_log if prepare_result else None,
            export_result.stderr_log if export_result else None,
            str(exc),
        )
        run.command_summary = _merge_logs(
            prepare_result.command_summary if prepare_result else None,
            export_result.command_summary if export_result else bridge.settings.host_agent_command,
        )

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _merge_logs(*values: str | None) -> str | None:
    merged = "\n\n".join(value for value in values if value)
    return merged or None
