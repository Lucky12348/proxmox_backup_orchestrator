from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import VMType, VirtualMachine
from app.services.proxmox_sync import list_preferred_inventory
from app.services.pbs_client import PBSClient


@dataclass
class PBSSyncSummary:
    matched_vms: int
    matched_cts: int
    total_snapshots_seen: int


@dataclass
class ProtectedInventoryItem:
    vm_id: int
    name: str
    vm_type: VMType
    last_backup_at: datetime | None
    protected: bool


def sync_pbs_inventory(
    db: Session,
    client: PBSClient | None = None,
    settings: Settings | None = None,
) -> PBSSyncSummary:
    current_settings = settings or get_settings()
    pbs_client = client or PBSClient(current_settings)
    snapshots = pbs_client.list_snapshots(current_settings.pbs_datastore)

    latest_by_key: dict[tuple[VMType, str], datetime] = {}

    for snapshot in snapshots:
        parsed = _parse_snapshot(snapshot)
        if parsed is None:
            continue

        key = (parsed["vm_type"], parsed["external_id"])
        previous = latest_by_key.get(key)
        if previous is None or parsed["backup_time"] > previous:
            latest_by_key[key] = parsed["backup_time"]

    matched_vms = 0
    matched_cts = 0

    for (vm_type, external_id), backup_time in latest_by_key.items():
        vm = db.scalar(
            select(VirtualMachine).where(
                VirtualMachine.source == "proxmox",
                VirtualMachine.external_id == external_id,
                VirtualMachine.vm_type == vm_type,
            )
        )
        if vm is None:
            continue

        vm.last_backup_at = backup_time
        db.add(vm)

        if vm_type == VMType.VM:
            matched_vms += 1
        else:
            matched_cts += 1

    db.commit()

    return PBSSyncSummary(
        matched_vms=matched_vms,
        matched_cts=matched_cts,
        total_snapshots_seen=len(snapshots),
    )


def list_pbs_inventory(db: Session) -> list[ProtectedInventoryItem]:
    inventory = list_preferred_inventory(db)
    return [
        ProtectedInventoryItem(
            vm_id=vm.id,
            name=vm.name,
            vm_type=vm.vm_type,
            last_backup_at=vm.last_backup_at,
            protected=bool(vm.enabled and vm.last_backup_at is not None),
        )
        for vm in inventory
    ]


def derive_latest_backup_status(db: Session) -> str | None:
    inventory = list_preferred_inventory(db)
    if any(vm.last_backup_at is not None for vm in inventory):
        return "success"
    return None


def _parse_snapshot(snapshot: dict) -> dict[str, VMType | str | datetime] | None:
    backup_time = _extract_backup_time(snapshot)
    backup_id = _extract_backup_id(snapshot)
    vmid = _extract_vmid(snapshot)
    vm_type = _extract_vm_type(snapshot)

    if backup_time is None or backup_id is None or vmid is None or vm_type is None:
        return None

    return {
        "backup_id": backup_id,
        "external_id": vmid,
        "vm_type": vm_type,
        "backup_time": backup_time,
    }


def _extract_backup_time(snapshot: dict) -> datetime | None:
    if isinstance(snapshot.get("backup-time"), (int, float)):
        return datetime.utcfromtimestamp(snapshot["backup-time"])

    for key in ("backup-time", "backup_time", "last-backup", "time"):
        value = snapshot.get(key)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue

    return None


def _extract_backup_id(snapshot: dict) -> str | None:
    for key in ("backup-id", "backup_id", "id"):
        value = snapshot.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_vmid(snapshot: dict) -> str | None:
    for key in ("vmid", "backup-id", "backup_id", "id"):
        value = snapshot.get(key)
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str):
            if value.isdigit():
                return value
            for segment in value.split("/"):
                if segment.isdigit():
                    return segment
            parts = value.split("-")
            for part in parts:
                if part.isdigit():
                    return part
    return None


def _extract_vm_type(snapshot: dict) -> VMType | None:
    for key in ("backup-type", "backup_type"):
        value = snapshot.get(key)
        if value == "qemu":
            return VMType.VM
        if value == "lxc":
            return VMType.CT

    backup_id = _extract_backup_id(snapshot)
    if backup_id:
        if backup_id.startswith("qemu"):
            return VMType.VM
        if backup_id.startswith("lxc") or backup_id.startswith("ct"):
            return VMType.CT

    return None
