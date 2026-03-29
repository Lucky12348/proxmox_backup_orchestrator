from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import VMType, VirtualMachine
from app.services.proxmox_client import ProxmoxClient


@dataclass
class ProxmoxSyncSummary:
    synced_vms_count: int
    synced_cts_count: int
    total_seen: int


def has_proxmox_inventory(db: Session) -> bool:
    statement = select(exists().where(VirtualMachine.source == "proxmox"))
    return bool(db.scalar(statement))


def list_preferred_inventory(db: Session) -> list[VirtualMachine]:
    source = "proxmox" if has_proxmox_inventory(db) else None
    statement = select(VirtualMachine)
    if source:
        statement = statement.where(VirtualMachine.source == source)

    return list(db.scalars(statement.order_by(VirtualMachine.name.asc())))


def sync_proxmox_inventory(
    db: Session,
    client: ProxmoxClient | None = None,
    settings: Settings | None = None,
) -> ProxmoxSyncSummary:
    current_settings = settings or get_settings()
    proxmox_client = client or ProxmoxClient(current_settings)

    qemu_vms = proxmox_client.list_qemu_vms(current_settings.pve_node_name)
    lxc_containers = proxmox_client.list_lxc_containers(current_settings.pve_node_name)
    seen_at = datetime.utcnow()

    synced_vms_count = _upsert_inventory_rows(
        db=db,
        items=qemu_vms,
        vm_type=VMType.VM,
        node_name=current_settings.pve_node_name,
        seen_at=seen_at,
    )
    synced_cts_count = _upsert_inventory_rows(
        db=db,
        items=lxc_containers,
        vm_type=VMType.CT,
        node_name=current_settings.pve_node_name,
        seen_at=seen_at,
    )

    db.commit()

    return ProxmoxSyncSummary(
        synced_vms_count=synced_vms_count,
        synced_cts_count=synced_cts_count,
        total_seen=synced_vms_count + synced_cts_count,
    )


def _upsert_inventory_rows(
    db: Session,
    items: list[dict],
    vm_type: VMType,
    node_name: str,
    seen_at: datetime,
) -> int:
    count = 0

    for item in items:
        external_id = str(item.get("vmid"))
        if not external_id:
            continue

        vm = db.scalar(
            select(VirtualMachine).where(
                VirtualMachine.source == "proxmox",
                VirtualMachine.external_id == external_id,
            )
        )

        if vm is None:
            vm = VirtualMachine(
                source="proxmox",
                external_id=external_id,
                critical=False,
            )

        vm.name = item.get("name") or f"{vm_type.value}-{external_id}"
        vm.vm_type = vm_type
        vm.size_gb = _extract_size_gb(item)
        vm.enabled = not bool(item.get("template")) and item.get("status") not in {None, "unknown"}
        vm.node_name = node_name
        vm.runtime_status = item.get("status")
        vm.last_seen_at = seen_at

        db.add(vm)
        count += 1

    return count


def _extract_size_gb(item: dict) -> int:
    maxdisk = item.get("maxdisk")
    maxmem = item.get("maxmem")

    if isinstance(maxdisk, (int, float)) and maxdisk > 0:
        return max(1, round(maxdisk / (1024**3)))

    if isinstance(maxmem, (int, float)) and maxmem > 0:
        return max(1, round(maxmem / (1024**3)))

    return 0
