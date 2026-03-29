from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import ExternalDisk
from app.schemas import ExternalDiskRead, ExternalDiskUpdate


router = APIRouter(prefix="/disks", tags=["external-disks"])


@router.get("", response_model=list[ExternalDiskRead])
def list_disks(db: DbSession) -> list[ExternalDisk]:
    return list(db.scalars(select(ExternalDisk).order_by(ExternalDisk.display_name.asc())))


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
