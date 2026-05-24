from fastapi import APIRouter, HTTPException, status
from sqlalchemy import exists, select

from app.api.dependencies import DbSession
from app.models import VirtualMachine
from app.schemas import VirtualMachineRead, VirtualMachineUpdate
from app.services.asset_ignores import get_asset_ignore_map, vm_read_payload


router = APIRouter(prefix="/vms", tags=["virtual-machines"])


@router.get("", response_model=list[VirtualMachineRead])
def list_vms(db: DbSession) -> list[dict]:
    proxmox_exists = bool(
        db.scalar(select(exists().where(VirtualMachine.source == "proxmox")))
    )
    statement = select(VirtualMachine)
    if proxmox_exists:
        statement = statement.where(VirtualMachine.source == "proxmox")

    vms = list(db.scalars(statement.order_by(VirtualMachine.name.asc())))
    ignore_map = get_asset_ignore_map(db, vms)
    return [vm_read_payload(vm, ignore_map) for vm in vms]


@router.patch("/{vm_id}", response_model=VirtualMachineRead)
def update_vm(vm_id: int, payload: VirtualMachineUpdate, db: DbSession) -> dict:
    vm = db.get(VirtualMachine, vm_id)
    if vm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vm, field, value)

    db.add(vm)
    db.commit()
    db.refresh(vm)
    ignore_map = get_asset_ignore_map(db, [vm])
    return vm_read_payload(vm, ignore_map)
