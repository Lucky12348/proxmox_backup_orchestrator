from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackupRunStatus, ExternalBackupMode, ExternalBackupRun, ExternalDisk
from app.services.external_backup_agent import get_external_backup_agent_bridge


@dataclass(frozen=True)
class ExternalBackupPlan:
    target_path: str
    mode: ExternalBackupMode
    preserves_existing_data: bool


def _normalize_base_path(disk: ExternalDisk) -> PurePosixPath:
    if disk.preferred_root_path:
        return PurePosixPath(disk.preferred_root_path)

    if disk.mount_path:
        return PurePosixPath(disk.mount_path)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Disk has no mount path or preferred root path for export planning.",
    )


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

    try:
        prepare_result = bridge.prepare_external_datastore(disk, plan.target_path)
        if not prepare_result.ok:
            raise RuntimeError(prepare_result.message)

        export_result = bridge.run_external_export(plan.target_path, settings.pbs_datastore)
        if not export_result.ok:
            raise RuntimeError(export_result.message)

        run.status = BackupRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        run.message = f"{prepare_result.message} {export_result.message}"
    except RuntimeError as exc:
        run.status = BackupRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.message = str(exc)

    db.add(run)
    db.commit()
    db.refresh(run)
    return run
