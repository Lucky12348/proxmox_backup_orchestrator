from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import ExternalDisk
from app.schemas import DiskPreparationRequest, DiskPreparationRunRead, ExternalDiskRead, ExternalDiskUpdate
from app.services.disk_preparations import get_disk_preparation_run, list_disk_preparation_runs, prepare_disk
from app.services.disks import list_preferred_disks


router = APIRouter(prefix="/disks", tags=["external-disks"])


@router.get("", response_model=list[ExternalDiskRead])
def list_disks(db: DbSession) -> list[ExternalDisk]:
    return list(db.scalars(select(ExternalDisk).order_by(ExternalDisk.display_name.asc())))


@router.get("/preferred", response_model=list[ExternalDiskRead])
def get_preferred_disks(db: DbSession) -> list[ExternalDisk]:
    return list_preferred_disks(db)


@router.patch("/{disk_id}", response_model=ExternalDiskRead)
def update_disk(
    disk_id: int,
    payload: ExternalDiskUpdate,
    db: DbSession,
) -> ExternalDisk:
    disk = db.get(ExternalDisk, disk_id)
    if disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(disk, field, value)

    db.add(disk)
    db.commit()
    db.refresh(disk)
    return disk


@router.post("/{disk_id}/prepare", response_model=DiskPreparationRunRead)
def prepare_disk_route(
    disk_id: int,
    payload: DiskPreparationRequest,
    db: DbSession,
) -> DiskPreparationRunRead:
    run = prepare_disk(
        db,
        disk_id=disk_id,
        mode=payload.mode,
        mount_base_path=payload.mount_base_path,
        confirm_destructive=payload.confirm_destructive,
    )
    return DiskPreparationRunRead.model_validate(run)


@router.get("/{disk_id}/preparation-runs", response_model=list[DiskPreparationRunRead])
def get_preparation_runs(disk_id: int, db: DbSession) -> list[DiskPreparationRunRead]:
    get_disk = db.get(ExternalDisk, disk_id)
    if get_disk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disk not found")

    return [
        DiskPreparationRunRead.model_validate(run)
        for run in list_disk_preparation_runs(db, disk_id)
    ]


@router.get("/preparation-runs/{run_id}", response_model=DiskPreparationRunRead)
def get_preparation_run(run_id: int, db: DbSession) -> DiskPreparationRunRead:
    run = get_disk_preparation_run(db, run_id)
    return DiskPreparationRunRead.model_validate(run)
