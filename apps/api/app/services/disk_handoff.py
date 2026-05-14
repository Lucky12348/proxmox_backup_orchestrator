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
            detail=(
                f"Failed to attach USB disk `{disk.serial_number}` to the PBS VM "
                f"using Proxmox USB mapping `{device['mapping']}`"
                f"{_selected_usb_detail(device)}: {exc}"
            ),
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
    strict_match = _find_strict_serial_match(devices, disk)
    if strict_match:
        return strict_match

    fallback_match = _find_safe_fallback_usb_match(devices, disk)
    if fallback_match:
        return fallback_match

    detail = (
        "No Proxmox USB passthrough candidate matched "
        f"disk serial `{disk.serial_number}`"
        f"{_disk_identity_suffix(disk)}. "
        f"Available USB devices: {_summarize_usb_devices(devices)}"
    )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _find_strict_serial_match(devices: list[dict[str, Any]], disk: ExternalDisk) -> dict[str, str] | None:
    serial = (disk.serial_number or "").strip()
    model = (disk.model_name or "").strip().casefold()
    for raw_device in devices:
        device_serial = _candidate_value(raw_device, "serial", "serial-number", "serialnumber")
        if device_serial != serial:
            continue
        device_model = (_candidate_value(raw_device, "product", "name", "model") or "").casefold()
        if model and device_model and model not in device_model:
            continue
        mapping = _qemu_usb_host_mapping(raw_device)
        if not mapping:
            continue
        return _build_usb_match(raw_device, mapping)
    return None


def _find_safe_fallback_usb_match(devices: list[dict[str, Any]], disk: ExternalDisk) -> dict[str, str] | None:
    if (disk.candidate_type or "").strip().casefold() != "usb":
        return None

    matches: list[dict[str, Any]] = []
    for raw_device in devices:
        if _has_serial_identity(raw_device):
            continue
        if not _qemu_usb_host_mapping(raw_device):
            continue
        if _is_forbidden_usb_passthrough_candidate(raw_device):
            continue
        if _is_likely_storage_usb_device(raw_device, disk):
            matches.append(raw_device)

    if len(matches) == 1:
        mapping = _qemu_usb_host_mapping(matches[0])
        if mapping:
            return _build_usb_match(matches[0], mapping)
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ambiguous Proxmox USB passthrough candidates matched "
                f"disk serial `{disk.serial_number}`"
                f"{_disk_identity_suffix(disk)}. "
                f"Matched USB devices: {_summarize_usb_devices(matches)}"
            ),
        )
    return None


def _summarize_usb_devices(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "none"

    summaries: list[str] = []
    for device in devices:
        manufacturer = _candidate_value(device, "manufacturer") or "unknown manufacturer"
        product = _candidate_value(device, "product", "name", "model") or "unknown product"
        vendid = _candidate_value(device, "vendid", "vendorid", "vendor_id") or "unknown vendid"
        prodid = _candidate_value(device, "prodid", "productid", "product_id") or "unknown prodid"
        usbpath = _usb_debug_path(device) or "missing usbpath"
        qemu_mapping = _qemu_usb_host_mapping(device) or "missing qemu mapping"
        usb_class = _candidate_value(device, "class", "classid", "usbclass", "usb_class") or "unknown class"
        summaries.append(
            f"{manufacturer} / {product} "
            f"(vendid={vendid}, prodid={prodid}, usbpath={usbpath}, "
            f"class={usb_class}, qemu_mapping={qemu_mapping})"
        )
    return "; ".join(summaries)


def _has_serial_identity(device: dict[str, Any]) -> bool:
    return bool(_candidate_value(device, "serial", "serial-number", "serialnumber"))


def _qemu_usb_host_mapping(device: dict[str, Any]) -> str | None:
    busnum = _candidate_value(device, "busnum", "bus")
    devnum = _candidate_value(device, "devnum", "device")
    if busnum and devnum:
        return f"{busnum}-{devnum}"

    vendid = _candidate_value(device, "vendid", "vendorid", "vendor_id")
    prodid = _candidate_value(device, "prodid", "productid", "product_id")
    if vendid and prodid:
        return f"{vendid}:{prodid}"

    return None


def _usb_debug_path(device: dict[str, Any]) -> str | None:
    return _candidate_value(device, "usbpath", "path", "port", "busport", "id")


def _build_usb_match(device: dict[str, Any], mapping: str) -> dict[str, str]:
    return {"mapping": mapping, "summary": _summarize_usb_devices([device])}


def _selected_usb_detail(device: dict[str, str]) -> str:
    summary = device.get("summary")
    if not summary:
        return ""
    return f" ({summary})"


def _is_forbidden_usb_passthrough_candidate(device: dict[str, Any]) -> bool:
    usb_class = (_candidate_value(device, "class", "classid", "usbclass", "usb_class") or "").casefold()
    if usb_class in {"3", "03", "0x03", "9", "09", "0x09", "hid", "hub"}:
        return True

    text = _normalized_usb_text(device)
    forbidden_terms = (
        "keyboard",
        "mouse",
        "ups",
        "uninterruptible",
        "power supply",
        "hub",
        "root hub",
        "host controller",
        "controller",
        "bluetooth",
        "receiver",
        "webcam",
        "camera",
        "audio",
        "headset",
        "microphone",
        "printer",
        "scanner",
        "smart card",
        "smartcard",
        "ethernet",
        "network",
        "wireless",
        "wifi",
    )
    return any(term in text for term in forbidden_terms)


def _is_likely_storage_usb_device(device: dict[str, Any], disk: ExternalDisk) -> bool:
    usb_class = (_candidate_value(device, "class", "classid", "usbclass", "usb_class") or "").casefold()
    if usb_class in {"8", "08", "0x08", "mass storage", "storage"}:
        return True

    text = _normalized_usb_text(device)
    storage_terms = (
        "storage",
        "drive",
        "disk",
        "hdd",
        "ssd",
        "flash",
        "thumb",
        "portable",
        "external",
        "backup",
        "passport",
        "elements",
        "easystore",
        "my book",
        "expansion",
        "game drive",
        "datatraveler",
        "cruzer",
        "ultra fit",
    )
    if any(term in text for term in storage_terms):
        return True

    known_storage_ids = {
        ("1058", "2630"),  # Western Digital Game Drive
    }
    vendid = (_candidate_value(device, "vendid", "vendorid", "vendor_id") or "").casefold()
    prodid = (_candidate_value(device, "prodid", "productid", "product_id") or "").casefold()
    if (vendid, prodid) in known_storage_ids:
        return True

    disk_text = " ".join(
        value.casefold()
        for value in (disk.model_name, disk.display_name)
        if isinstance(value, str) and value.strip()
    )
    if disk_text and _meaningful_shared_token(disk_text, text):
        return True

    return False


def _normalized_usb_text(device: dict[str, Any]) -> str:
    values = [
        _candidate_value(device, "manufacturer"),
        _candidate_value(device, "product", "name", "model"),
        _candidate_value(device, "vendid", "vendorid", "vendor_id"),
        _candidate_value(device, "prodid", "productid", "product_id"),
    ]
    return " ".join(value.casefold() for value in values if value)


def _meaningful_shared_token(left: str, right: str) -> bool:
    ignored = {"usb", "disk", "drive", "storage", "external", "portable"}
    left_tokens = {token for token in _split_match_tokens(left) if token not in ignored}
    right_tokens = {token for token in _split_match_tokens(right) if token not in ignored}
    return bool(left_tokens & right_tokens)


def _split_match_tokens(value: str) -> list[str]:
    return [token for token in "".join(char if char.isalnum() else " " for char in value).split() if len(token) >= 3]


def _disk_identity_suffix(disk: ExternalDisk) -> str:
    parts = []
    if disk.model_name:
        parts.append(f"model `{disk.model_name}`")
    if disk.display_name:
        parts.append(f"display `{disk.display_name}`")
    if not parts:
        return ""
    return " (" + ", ".join(parts) + ")"


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
        if isinstance(value, int):
            return str(value)
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
