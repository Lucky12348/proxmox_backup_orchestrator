from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackupRunStatus, DiskPreparationMode, DiskPreparationRun, ExternalDisk
from app.services.disk_preparation_agent import get_disk_preparation_agent_bridge


def get_disk_or_404(db: Session, disk_id: int) -> ExternalDisk:
    disk = db.get(ExternalDisk, disk_id)
    if disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")
    return disk


def list_disk_preparation_runs(db: Session, disk_id: int) -> list[DiskPreparationRun]:
    return list(
        db.scalars(
            select(DiskPreparationRun)
            .where(DiskPreparationRun.disk_id == disk_id)
            .order_by(DiskPreparationRun.started_at.desc())
        )
    )


def get_disk_preparation_run(db: Session, run_id: int) -> DiskPreparationRun:
    run = db.get(DiskPreparationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preparation run not found")
    return run


def prepare_disk(
    db: Session,
    disk_id: int,
    mode: DiskPreparationMode,
    mount_base_path: str | None,
    confirm_destructive: bool,
) -> DiskPreparationRun:
    disk = get_disk_or_404(db, disk_id)
    if not disk.connected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disk must be connected before preparation can start.",
        )

    bridge = get_disk_preparation_agent_bridge()
    inspection = bridge.inspect_disk(disk, mount_base_path)
    if not inspection.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=inspection.message)

    if mode == DiskPreparationMode.DEDICATED_BACKUP and not confirm_destructive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dedicated backup preparation requires destructive confirmation.",
        )

    if mode == DiskPreparationMode.PRESERVE_EXISTING_DATA and not inspection.filesystem_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preserve-existing-data mode requires an existing filesystem.",
        )

    now = datetime.utcnow()
    run = DiskPreparationRun(
        disk_id=disk.id,
        mode=mode,
        status=BackupRunStatus.PENDING,
        started_at=now,
        finished_at=None,
        message=None,
        mount_path=None,
        filesystem_type=None,
        created_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    run.status = BackupRunStatus.RUNNING
    db.add(run)
    db.commit()
    db.refresh(run)

    result = bridge.prepare_disk(disk, mode, mount_base_path)
    if result.ok:
        run.status = BackupRunStatus.SUCCESS
        run.finished_at = datetime.utcnow()
        run.message = result.message
        run.mount_path = result.mount_path
        run.filesystem_type = result.filesystem_type

        disk.mount_path = result.mount_path
        disk.filesystem_type = result.filesystem_type
        disk.connected = True
        disk.last_seen_at = datetime.utcnow()
        db.add(disk)
    else:
        run.status = BackupRunStatus.FAILED
        run.finished_at = datetime.utcnow()
        run.message = result.message

    db.add(run)
    db.commit()
    db.refresh(run)
    return run
