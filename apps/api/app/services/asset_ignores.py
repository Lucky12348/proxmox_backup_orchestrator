from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssetIgnore, VirtualMachine

AssetKey = tuple[str, str, str]


def normalize_asset_key(source: str | None, node: str | None, vmid: str | int | None) -> AssetKey:
    return ((source or "proxmox").strip(), (node or "").strip(), str(vmid or "").strip())


def asset_key_for_vm(vm: VirtualMachine) -> AssetKey:
    return normalize_asset_key(vm.source, vm.node_name, vm.external_id or vm.id)


def list_asset_ignores(db: Session) -> list[AssetIgnore]:
    return list(db.scalars(select(AssetIgnore).order_by(AssetIgnore.source, AssetIgnore.node, AssetIgnore.vmid)))


def get_asset_ignore_map(db: Session, vms: Iterable[VirtualMachine] | None = None) -> dict[AssetKey, AssetIgnore]:
    statement = select(AssetIgnore)
    if vms is not None:
        keys = {asset_key_for_vm(vm) for vm in vms}
        if not keys:
            return {}
        ignores = list(db.scalars(statement))
        return {normalize_asset_key(item.source, item.node, item.vmid): item for item in ignores if normalize_asset_key(item.source, item.node, item.vmid) in keys}

    return {normalize_asset_key(item.source, item.node, item.vmid): item for item in db.scalars(statement)}


def is_vm_ignored(vm: VirtualMachine, ignore_map: dict[AssetKey, AssetIgnore] | None = None) -> bool:
    current_map = ignore_map or {}
    item = current_map.get(asset_key_for_vm(vm))
    return bool(item and item.ignored)


def ignored_reason_for_vm(vm: VirtualMachine, ignore_map: dict[AssetKey, AssetIgnore] | None = None) -> str | None:
    current_map = ignore_map or {}
    item = current_map.get(asset_key_for_vm(vm))
    return item.reason if item and item.ignored else None


def upsert_asset_ignore(
    db: Session,
    *,
    source: str,
    node: str,
    vmid: str,
    ignored: bool,
    reason: str | None = None,
) -> AssetIgnore:
    key = normalize_asset_key(source, node, vmid)
    item = db.scalar(
        select(AssetIgnore).where(
            AssetIgnore.source == key[0],
            AssetIgnore.node == key[1],
            AssetIgnore.vmid == key[2],
        )
    )
    if item is None:
        item = AssetIgnore(source=key[0], node=key[1], vmid=key[2])

    item.ignored = ignored
    item.reason = reason
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def vm_read_payload(vm: VirtualMachine, ignore_map: dict[AssetKey, AssetIgnore] | None = None) -> dict:
    item = (ignore_map or {}).get(asset_key_for_vm(vm))
    ignored = bool(item and item.ignored)
    return {
        "id": vm.id,
        "name": vm.name,
        "vm_type": vm.vm_type,
        "critical": vm.critical,
        "size_gb": vm.size_gb,
        "enabled": vm.enabled,
        "source": vm.source,
        "external_id": vm.external_id,
        "node_name": vm.node_name,
        "runtime_status": vm.runtime_status,
        "last_seen_at": vm.last_seen_at,
        "last_backup_at": vm.last_backup_at,
        "ignored": ignored,
        "ignore_reason": item.reason if ignored and item else None,
    }
