from app.schemas.backup_run import BackupRunRead
from app.schemas.external_disk import ExternalDiskRead, ExternalDiskUpdate
from app.schemas.integrations_proxmox import ProxmoxStatusRead, ProxmoxSyncRead
from app.schemas.overview import OverviewRead
from app.schemas.virtual_machine import VirtualMachineRead, VirtualMachineUpdate

__all__ = [
    "BackupRunRead",
    "ExternalDiskRead",
    "ExternalDiskUpdate",
    "ProxmoxStatusRead",
    "ProxmoxSyncRead",
    "OverviewRead",
    "VirtualMachineRead",
    "VirtualMachineUpdate",
]
