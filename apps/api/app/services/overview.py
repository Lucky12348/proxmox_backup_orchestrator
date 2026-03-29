from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import BackupRun, ExternalDisk, VirtualMachine


@dataclass
class OverviewMetrics:
    total_vms: int
    protected_vms: int
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

    total_vms = db.scalar(select(func.count(VirtualMachine.id)).where(*vm_scope)) or 0
    enabled_vms = db.scalar(
        select(func.count(VirtualMachine.id)).where(
            *vm_scope,
            VirtualMachine.enabled.is_(True),
        )
    ) or 0
    protected_vms = db.scalar(
        select(func.count(VirtualMachine.id)).where(
            *vm_scope,
            VirtualMachine.enabled.is_(True),
            VirtualMachine.last_backup_at.is_not(None),
        )
    ) or 0
    connected_disks = db.scalar(
        select(func.count(ExternalDisk.id)).where(ExternalDisk.connected.is_(True))
    ) or 0
    latest_backup = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))
    recent_backup_runs = list(
        db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(5))
    )

    coverage_percent = 0.0
    if enabled_vms:
        coverage_percent = round((protected_vms / enabled_vms) * 100, 1)

    return OverviewMetrics(
        total_vms=total_vms,
        protected_vms=protected_vms,
        coverage_percent=coverage_percent,
        connected_disks=connected_disks,
        latest_backup_status=latest_backup.status.value if latest_backup else None,
        recent_backup_runs=recent_backup_runs,
    )
