from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import BackupRun, ExternalDisk, VirtualMachine
from app.services.asset_ignores import get_asset_ignore_map, is_vm_ignored
from app.services.disks import has_agent_disks
from app.services.pbs_sync import derive_latest_backup_status


@dataclass
class OverviewMetrics:
    total_vms: int
    protected_vms: int
    ignored_vms: int
    coverage_percent: float
    connected_disks: int
    latest_backup_status: str | None
    recent_backup_runs: list[BackupRun]


def get_overview_metrics(db: Session) -> OverviewMetrics:
    use_proxmox_inventory = bool(
        db.scalar(select(exists().where(VirtualMachine.source == "proxmox")))
    )

    vm_scope = []
    if use_proxmox_inventory:
        vm_scope.append(VirtualMachine.source == "proxmox")

    scoped_vms = list(
        db.scalars(
            select(VirtualMachine).where(
                *vm_scope,
                VirtualMachine.enabled.is_(True),
            )
        )
    )
    ignore_map = get_asset_ignore_map(db, scoped_vms)
    active_vms = [vm for vm in scoped_vms if not is_vm_ignored(vm, ignore_map)]
    ignored_vms = len(scoped_vms) - len(active_vms)
    enabled_vms = len(active_vms)
    protected_vms = sum(1 for vm in active_vms if vm.last_backup_at is not None)
    disk_scope = [ExternalDisk.active.is_(True), ExternalDisk.connected.is_(True)]
    if has_agent_disks(db):
        disk_scope.append(ExternalDisk.source == "agent")

    connected_disks = db.scalar(select(func.count(ExternalDisk.id)).where(*disk_scope)) or 0
    latest_backup = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))
    recent_backup_runs = list(
        db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(5))
    )

    coverage_percent = 0.0
    if enabled_vms:
        coverage_percent = round((protected_vms / enabled_vms) * 100, 1)

    latest_backup_status = latest_backup.status.value if latest_backup else derive_latest_backup_status(db)

    return OverviewMetrics(
        total_vms=enabled_vms,
        protected_vms=protected_vms,
        ignored_vms=ignored_vms,
        coverage_percent=coverage_percent,
        connected_disks=connected_disks,
        latest_backup_status=latest_backup_status,
        recent_backup_runs=recent_backup_runs,
    )
