from dataclasses import dataclass
from time import sleep
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExternalDisk
from app.services.host_agent import HostAgentError, get_pbs_agent_client
from app.services.proxmox_client import ProxmoxClient


@dataclass(frozen=True)
class DiskHandoffStatus:
    disk_id: int
    serial_number: str
    handoff_status: str
    proxmox_usb_mapping: str | None
    pbs_handoff_slot: str | None
    pbs_visible: bool
    pbs_device_path: str | None
    message: str


def handoff_disk_to_pbs(db: Session, disk: ExternalDisk, *, confirmation: bool) -> DiskHandoffStatus:
    if not confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="USB handoff to PBS requires explicit confirmation.",
        )
    if not disk.connected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Disk must be connected on Proxmox.")
    if disk.mount_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disk is still mounted on the Proxmox host. Unmount it before PBS handoff.",
        )

    settings = get_settings()
    client = ProxmoxClient(settings)
    device = _find_matching_usb_device(client.list_usb_devices(settings.pve_node_name), disk)
    vm_config = client.get_qemu_config(settings.pbs_execution_vm_node, settings.pbs_execution_vm_id)
    slot = disk.pbs_handoff_slot or _find_free_usb_slot(vm_config)

    try:
        client.set_qemu_usb_device(settings.pbs_execution_vm_node, settings.pbs_execution_vm_id, slot, device["mapping"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to attach USB disk `{disk.serial_number}` to the PBS VM: {exc}",
        ) from exc

    disk.handoff_status = "attached_to_pbs"
    disk.proxmox_usb_mapping = device["mapping"]
    disk.pbs_handoff_slot = slot
    disk.pbs_visible = False
    disk.pbs_device_path = None
    db.add(disk)
    db.commit()
    db.refresh(disk)

    return wait_for_pbs_disk_visibility(db, disk, attempts=8, delay_seconds=2.0)


def detach_disk_from_pbs(db: Session, disk: ExternalDisk) -> DiskHandoffStatus:
    settings = get_settings()
    if not disk.pbs_handoff_slot:
        return _build_status(disk, "Disk is not currently attached to the PBS VM.")

    client = ProxmoxClient(settings)
    try:
        client.delete_qemu_usb_device(settings.pbs_execution_vm_node, settings.pbs_execution_vm_id, disk.pbs_handoff_slot)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to detach USB disk `{disk.serial_number}` from the PBS VM: {exc}",
        ) from exc

    disk.handoff_status = "detected_on_proxmox"
    disk.pbs_visible = False
    disk.pbs_device_path = None
    disk.pbs_handoff_slot = None
    db.add(disk)
    db.commit()
    db.refresh(disk)
    return _build_status(disk, "Disk detached from the PBS VM.")


def wait_for_pbs_disk_visibility(
    db: Session,
    disk: ExternalDisk,
    *,
    attempts: int = 5,
    delay_seconds: float = 1.5,
) -> DiskHandoffStatus:
    pbs_agent = get_pbs_agent_client()
    last_error: str | None = None

    for _ in range(attempts):
        try:
            result = pbs_agent.post("/inspect-disk", {"disk": disk.serial_number})
        except HostAgentError as exc:
            last_error = str(exc)
            sleep(delay_seconds)
            continue

        device_path = _extract_pbs_device_path(result.payload)
        disk.pbs_visible = True
        disk.pbs_device_path = device_path
        disk.handoff_status = "visible_on_pbs"
        db.add(disk)
        db.commit()
        db.refresh(disk)
        return _build_status(disk, f"Disk is now visible on PBS as {device_path or disk.serial_number}.")

    disk.pbs_visible = False
    disk.handoff_status = "attached_to_pbs"
    db.add(disk)
    db.commit()
    db.refresh(disk)
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=(
            "The disk was attached to the PBS VM, but the PBS agent could not see it yet."
            + (f" Last error: {last_error}" if last_error else "")
        ),
    )


def get_pbs_disk_visibility(db: Session, disk: ExternalDisk) -> DiskHandoffStatus:
    pbs_agent = get_pbs_agent_client()
    try:
        result = pbs_agent.post("/inspect-disk", {"disk": disk.serial_number})
    except HostAgentError as exc:
        return _build_status(disk, f"PBS visibility check failed: {exc}")

    device_path = _extract_pbs_device_path(result.payload)
    if device_path:
        disk.pbs_visible = True
        disk.pbs_device_path = device_path
        disk.handoff_status = "visible_on_pbs"
        db.add(disk)
        db.commit()
        db.refresh(disk)
        return _build_status(disk, f"Disk is visible on PBS as {device_path}.")

    disk.pbs_visible = False
    db.add(disk)
    db.commit()
    db.refresh(disk)
    return _build_status(disk, "Disk is not yet visible on PBS.")


def _find_matching_usb_device(devices: list[dict[str, Any]], disk: ExternalDisk) -> dict[str, str]:
    serial = disk.serial_number.strip()
    model = (disk.model_name or "").strip().lower()
    for raw_device in devices:
        device_serial = _candidate_value(raw_device, "serial", "serial-number", "serialnumber")
        if device_serial != serial:
            continue
        device_model = (_candidate_value(raw_device, "product", "name", "model") or "").lower()
        if model and device_model and model not in device_model:
            continue
        mapping = _candidate_value(raw_device, "usbpath", "path", "port", "busport", "id")
        if not mapping:
            break
        return {"mapping": mapping}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            f"No strict Proxmox USB passthrough candidate matched serial `{disk.serial_number}`."
        ),
    )


def _find_free_usb_slot(vm_config: dict[str, Any]) -> str:
    for index in range(5):
        slot = f"usb{index}"
        if not vm_config.get(slot):
            return slot
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No free USB passthrough slot is available on the PBS VM.",
    )


def _extract_pbs_device_path(payload: dict[str, Any]) -> str | None:
    disk_info = payload.get("disk")
    if isinstance(disk_info, dict):
        path = disk_info.get("path")
        if isinstance(path, str) and path.strip():
            return path.strip()
    return None


def _candidate_value(device: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _build_status(disk: ExternalDisk, message: str) -> DiskHandoffStatus:
    return DiskHandoffStatus(
        disk_id=disk.id,
        serial_number=disk.serial_number,
        handoff_status=disk.handoff_status or "detected_on_proxmox",
        proxmox_usb_mapping=disk.proxmox_usb_mapping,
        pbs_handoff_slot=disk.pbs_handoff_slot,
        pbs_visible=disk.pbs_visible,
        pbs_device_path=disk.pbs_device_path,
        message=message,
    )
