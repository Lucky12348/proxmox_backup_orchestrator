from datetime import datetime
from pathlib import PurePosixPath

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.disk_handoff import detach_disk_from_pbs
from app.services.external_backup_agent import AgentCommandError, get_external_backup_agent_bridge
from app.services.external_backup_execution import build_dedicated_datastore_name
from app.services.external_backups import append_external_backup_run_log


RUNNING_EJECT_REFUSAL = "Impossible d’éjecter le disque: une tâche PBS est en cours."


def eject_dedicated_external_disk(db: Session, disk_id: int) -> ExternalDisk:
    disk = db.get(ExternalDisk, disk_id)
    if disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")
    if not disk.dedicated_backup_disk and not disk.prepared_as_pbs_datastore:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only dedicated PBS datastore disks can be ejected from this workflow.",
        )

    active_run = db.scalar(
        select(ExternalBackupRun)
        .where(
            ExternalBackupRun.disk_id == disk.id,
            ExternalBackupRun.status.in_([BackupRunStatus.PENDING, BackupRunStatus.RUNNING]),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=RUNNING_EJECT_REFUSAL)

    datastore_name = disk.pbs_datastore_name or build_dedicated_datastore_name(disk.serial_number)
    mount_path = disk.pbs_mount_path or str(PurePosixPath("/mnt/pbo") / disk.serial_number / "pbs-datastore")
    run = _create_eject_activity(db, disk, datastore_name, mount_path)

    try:
        append_external_backup_run_log(
            db,
            run.id,
            step="eject",
            message="Unmounting dedicated PBS datastore on PBS.",
        )
        result = get_external_backup_agent_bridge().eject_dedicated_pbs_datastore(
            serial=disk.serial_number,
            datastore_name=datastore_name,
            mount_path=mount_path,
        )
        if not result.ok:
            raise AgentCommandError(
                result.message,
                stdout_log=result.stdout_log,
                stderr_log=result.stderr_log,
                command_summary=result.command_summary,
                execution_cwd=result.execution_cwd,
                return_code=result.return_code,
            )

        append_external_backup_run_log(
            db,
            run.id,
            step="eject",
            message="Detaching USB disk from PBS VM.",
            line=result.stdout_log,
        )
        detach_status = detach_disk_from_pbs(db, disk)
        db.refresh(disk)
        disk.connected = False
        disk.pbs_visible = False
        disk.pbs_device_path = None
        disk.pbs_handoff_slot = None
        disk.proxmox_usb_mapping = None
        disk.handoff_status = "ejected"
        db.add(disk)

        run.status = BackupRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        run.message = "Le disque est prêt. Vous pouvez le retirer."
        run.stdout_log = _merge_logs(run.stdout_log, result.stdout_log, detach_status.message)
        run.stderr_log = _merge_logs(run.stderr_log, result.stderr_log)
        run.command_summary = result.command_summary
        run.execution_cwd = result.execution_cwd
        run.return_code = result.return_code
        run.current_step = "ejected"
        run.progress_message = run.message
        run.last_log_at = datetime.utcnow()
        db.add(run)
        db.commit()
        db.refresh(disk)
        return disk
    except AgentCommandError as exc:
        _finish_eject_activity_failed(db, run, str(exc), exc.stdout_log, exc.stderr_log, exc.command_summary, exc.execution_cwd, exc.return_code)
        if "running" in str(exc).casefold() or "sync job" in str(exc).casefold() or "task" in str(exc).casefold():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=RUNNING_EJECT_REFUSAL) from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except HTTPException as exc:
        _finish_eject_activity_failed(db, run, str(exc.detail), None, str(exc.detail), None, None, None)
        raise


def _create_eject_activity(db: Session, disk: ExternalDisk, datastore_name: str, mount_path: str) -> ExternalBackupRun:
    now = datetime.utcnow()
    run = ExternalBackupRun(
        disk_id=disk.id,
        status=BackupRunStatus.RUNNING,
        started_at=now,
        finished_at=None,
        target_path=mount_path,
        datastore_name=datastore_name,
        message=None,
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=None,
        current_step="eject",
        progress_message="Preparing external disk for safe removal.",
        last_log_at=now,
        mode=ExternalBackupMode.DEDICATED,
        created_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_eject_activity_failed(
    db: Session,
    run: ExternalBackupRun,
    message: str,
    stdout_log: str | None,
    stderr_log: str | None,
    command_summary: str | None,
    execution_cwd: str | None,
    return_code: int | None,
) -> None:
    run.status = BackupRunStatus.FAILED
    run.finished_at = datetime.utcnow()
    run.message = message
    run.stdout_log = _merge_logs(run.stdout_log, stdout_log)
    run.stderr_log = _merge_logs(run.stderr_log, stderr_log, message)
    run.command_summary = command_summary
    run.execution_cwd = execution_cwd
    run.return_code = return_code
    run.current_step = "failure"
    run.progress_message = message
    run.last_log_at = datetime.utcnow()
    db.add(run)
    db.commit()


def _merge_logs(*values: str | None) -> str | None:
    merged = "\n\n".join(value for value in values if value)
    return merged or None
