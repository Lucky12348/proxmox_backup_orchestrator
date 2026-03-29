from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DiskAssignment, ExternalDisk, VirtualMachine
from app.services.disks import list_preferred_disks
from app.services.proxmox_sync import list_preferred_inventory


@dataclass
class DiskPlanningSummary:
    disk_id: int
    serial_number: str
    display_name: str
    trusted: bool
    available_capacity_gb: int
    total_planned_gb: int
    planned_vm_count: int
    unplanned_vm_count: int
    fits_all: bool


@dataclass
class PlanningOverview:
    trusted_disk_count: int
    plannable_vm_count: int
    planned_vm_count: int
    planning_coverage_percent: float


def get_available_capacity_gb(disk: ExternalDisk) -> int:
    base_capacity = disk.usable_capacity_gb if disk.usable_capacity_gb is not None else disk.capacity_gb
    return max(0, base_capacity - disk.reserved_capacity_gb)


def get_disk_planning(db: Session) -> list[DiskPlanningSummary]:
    preferred_disks = list_preferred_disks(db)
    trusted_disks = [disk for disk in preferred_disks if disk.trusted]
    plannable_vms = [vm for vm in list_preferred_inventory(db) if vm.enabled]
    assignments = list(db.scalars(select(DiskAssignment)))

    pinned_by_vm = {assignment.vm_id: assignment.disk_id for assignment in assignments if assignment.pinned}
    disk_capacity = {disk.id: get_available_capacity_gb(disk) for disk in trusted_disks}
    disk_planned: dict[int, list[VirtualMachine]] = {disk.id: [] for disk in trusted_disks}
    unplanned_vms: list[VirtualMachine] = []

    for vm in sorted(plannable_vms, key=lambda item: item.size_gb, reverse=True):
        pinned_disk_id = pinned_by_vm.get(vm.id)
        if pinned_disk_id is not None:
            remaining = disk_capacity.get(pinned_disk_id, -1)
            if remaining >= vm.size_gb:
                disk_capacity[pinned_disk_id] -= vm.size_gb
                disk_planned[pinned_disk_id].append(vm)
            else:
                unplanned_vms.append(vm)
            continue

        placed = False
        for disk in trusted_disks:
            if disk_capacity[disk.id] >= vm.size_gb:
                disk_capacity[disk.id] -= vm.size_gb
                disk_planned[disk.id].append(vm)
                placed = True
                break

        if not placed:
            unplanned_vms.append(vm)

    unplanned_count = len(unplanned_vms)
    return [
        DiskPlanningSummary(
            disk_id=disk.id,
            serial_number=disk.serial_number,
            display_name=disk.display_name,
            trusted=disk.trusted,
            available_capacity_gb=disk_capacity[disk.id],
            total_planned_gb=sum(vm.size_gb for vm in disk_planned[disk.id]),
            planned_vm_count=len(disk_planned[disk.id]),
            unplanned_vm_count=unplanned_count,
            fits_all=unplanned_count == 0,
        )
        for disk in trusted_disks
    ]


def get_unplanned_assets(db: Session) -> list[VirtualMachine]:
    preferred_disks = list_preferred_disks(db)
    trusted_disks = [disk for disk in preferred_disks if disk.trusted]
    plannable_vms = [vm for vm in list_preferred_inventory(db) if vm.enabled]
    assignments = list(db.scalars(select(DiskAssignment)))
    pinned_by_vm = {assignment.vm_id: assignment.disk_id for assignment in assignments if assignment.pinned}
    disk_capacity = {disk.id: get_available_capacity_gb(disk) for disk in trusted_disks}
    unplanned: list[VirtualMachine] = []

    for vm in sorted(plannable_vms, key=lambda item: item.size_gb, reverse=True):
        pinned_disk_id = pinned_by_vm.get(vm.id)
        if pinned_disk_id is not None:
            remaining = disk_capacity.get(pinned_disk_id, -1)
            if remaining >= vm.size_gb:
                disk_capacity[pinned_disk_id] -= vm.size_gb
            else:
                unplanned.append(vm)
            continue

        for disk in trusted_disks:
            if disk_capacity[disk.id] >= vm.size_gb:
                disk_capacity[disk.id] -= vm.size_gb
                break
        else:
            unplanned.append(vm)

    return unplanned


def get_planning_overview(db: Session) -> PlanningOverview:
    trusted_disks = [disk for disk in list_preferred_disks(db) if disk.trusted]
    plannable_vms = [vm for vm in list_preferred_inventory(db) if vm.enabled]
    unplanned = get_unplanned_assets(db)
    planned_vm_count = len(plannable_vms) - len(unplanned)
    coverage = 0.0
    if plannable_vms:
        coverage = round((planned_vm_count / len(plannable_vms)) * 100, 1)

    return PlanningOverview(
        trusted_disk_count=len(trusted_disks),
        plannable_vm_count=len(plannable_vms),
        planned_vm_count=planned_vm_count,
        planning_coverage_percent=coverage,
    )
