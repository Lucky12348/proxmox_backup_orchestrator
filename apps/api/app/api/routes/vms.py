from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models import VirtualMachine
from app.schemas import VirtualMachineRead, VirtualMachineUpdate


router = APIRouter(prefix="/vms", tags=["virtual-machines"])


@router.get("", response_model=list[VirtualMachineRead])
def list_vms(db: DbSession) -> list[VirtualMachine]:
    return list(db.scalars(select(VirtualMachine).order_by(VirtualMachine.name.asc())))


@router.patch("/{vm_id}", response_model=VirtualMachineRead)
def update_vm(vm_id: int, payload: VirtualMachineUpdate, db: DbSession) -> VirtualMachine:
    vm = db.get(VirtualMachine, vm_id)
    if vm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VM not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vm, field, value)

    db.add(vm)
    db.commit()
    db.refresh(vm)
    return vm
