import argparse
import json
import logging
import os
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")

EXCLUDED_DEVICE_PREFIXES = ("loop", "dm-", "zd", "sr")
SYSTEM_MOUNTPOINTS = {"/", "/boot", "/boot/efi"}
SYSTEM_FS_MARKERS = {"LVM2_member", "zfs_member"}


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentSettings:
    api_base_url: str = os.getenv("AGENT_API_BASE_URL", "http://localhost:8000/api/v1")
    hostname: str = os.getenv("AGENT_HOSTNAME", socket.gethostname())
    agent_version: str = os.getenv("AGENT_VERSION", "0.1.0")
    timeout_seconds: float = float(os.getenv("AGENT_TIMEOUT_SECONDS", "10"))
    include_non_usb_candidates: bool = parse_bool(
        os.getenv("AGENT_INCLUDE_NON_USB_CANDIDATES"),
        default=False,
    )


def post_heartbeat(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "agent_version": settings.agent_version,
        "observed_at": current_timestamp(),
    }
    post_json(settings, "/agent/heartbeat", payload)
    logger.info("Heartbeat sent for host %s", settings.hostname)


def post_real_disk_report(settings: AgentSettings) -> None:
    disks = discover_real_disks(settings)
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": disks,
    }
    post_json(settings, "/agent/disks/report", payload)
    logger.info("Real disk report sent for host %s with %s disks", settings.hostname, len(disks))


def post_mock_disk_report(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": mock_disks(),
    }
    post_json(settings, "/agent/disks/report", payload)
    logger.info("Mock disk report sent for host %s", settings.hostname)


def sync_state(settings: AgentSettings) -> None:
    post_heartbeat(settings)
    post_real_disk_report(settings)


def prepare_external_datastore(mount_path: str, target_path: str) -> None:
    mount = Path(mount_path)
    target = Path(target_path)
    if not mount.exists():
        raise FileNotFoundError(f"Mount path does not exist: {mount_path}")

    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "mount_path": str(mount),
        "target_path": str(target),
        "message": "Target directory is ready for external datastore export.",
    }
    print(json.dumps(payload))
    logger.info("Prepared external datastore target %s", target)


def run_external_export(target_path: str, datastore_name: str) -> None:
    target = Path(target_path)
    if not target.exists():
        raise FileNotFoundError(f"Target path does not exist: {target_path}")

    payload = {
        "ok": True,
        "target_path": str(target),
        "datastore_name": datastore_name,
        "message": (
            "Stub export boundary: would run a PBS-native-like export using "
            f"datastore '{datastore_name}' into '{target_path}'."
        ),
    }
    print(json.dumps(payload))
    logger.info(
        "Stub external export for datastore %s into %s",
        datastore_name,
        target_path,
    )


def discover_real_disks(settings: AgentSettings) -> list[dict[str, Any]]:
    lsblk_output = run_command(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,KNAME,TYPE,MODEL,SERIAL,SIZE,RM,ROTA,TRAN,MOUNTPOINT,FSTYPE,HOTPLUG,PKNAME",
        ]
    )
    payload = json.loads(lsblk_output)
    devices = payload.get("blockdevices", [])

    discovered: list[dict[str, Any]] = []
    for device in devices:
        if not is_candidate_disk(device):
            continue

        udev_props = load_udev_properties(device_name(device))
        serial_number = disk_serial_number(device, udev_props)
        if not serial_number:
            continue

        reason = get_exclusion_reason(device, udev_props)
        if reason is not None:
            logger.debug("Skipping %s: %s", device_name(device), reason)
            continue

        candidate = classify_candidate(device, udev_props, settings)
        if candidate is None:
            logger.debug("Skipping %s: not clearly external/removable", device_name(device))
            continue

        candidate_type, detection_reason = candidate
        disk_report = build_disk_report(
            device=device,
            udev_props=udev_props,
            serial_number=serial_number,
            candidate_type=candidate_type,
            detection_reason=detection_reason,
        )
        if disk_report:
            discovered.append(disk_report)

    return deduplicate_disk_reports(discovered)


def is_candidate_disk(device: dict[str, Any]) -> bool:
    name = device_name(device)
    if device.get("type") != "disk":
        return False

    return not any(name.startswith(prefix) for prefix in EXCLUDED_DEVICE_PREFIXES)


def get_exclusion_reason(device: dict[str, Any], udev_props: dict[str, str]) -> str | None:
    partitions = flatten_partitions(device.get("children", []))
    filesystem_markers = {
        part.get("fstype")
        for part in [device, *partitions]
        if isinstance(part.get("fstype"), str)
    }
    mountpoints = {
        part.get("mountpoint")
        for part in [device, *partitions]
        if isinstance(part.get("mountpoint"), str) and part.get("mountpoint")
    }
    all_device_names = {device_name(device), *(device_name(part) for part in partitions)}

    if mountpoints & SYSTEM_MOUNTPOINTS:
        return "backs system mount"

    if filesystem_markers & SYSTEM_FS_MARKERS:
        return "belongs to lvm/zfs system storage"

    if any("rpool" in (udev_props.get(key, "").lower()) for key in udev_props):
        return "belongs to zfs root pool"

    if any("pve" in (mount or "").lower() for mount in mountpoints):
        return "used by proxmox storage mount"

    if any(name.startswith("zd") or name.startswith("dm-") for name in all_device_names):
        return "backs virtual or mapped storage"

    return None


def classify_candidate(
    device: dict[str, Any],
    udev_props: dict[str, str],
    settings: AgentSettings,
) -> tuple[str, str] | None:
    transport = (device.get("tran") or "").lower()
    removable = str(device.get("rm", "0")) == "1"
    hotplug = str(device.get("hotplug", "0")) == "1"
    udev_bus = udev_props.get("ID_BUS", "").lower()
    devpath = udev_props.get("DEVPATH", "").lower()
    usb_indicators = any(
        [
            transport == "usb",
            udev_bus == "usb",
            "usb" in devpath,
            "ID_USB_DRIVER" in udev_props,
            "ID_USB_MODEL" in udev_props,
        ]
    )

    if usb_indicators:
        return ("usb", "usb-connected disk")

    if removable or hotplug:
        return ("removable", "removable disk")

    if settings.include_non_usb_candidates:
        return ("standalone", "standalone non-system disk (advanced mode)")

    return None


def deduplicate_disk_reports(disks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for disk in disks:
        key = str(disk.get("serial_number") or disk.get("display_name"))
        existing = deduplicated.get(key)
        if existing is None or disk_priority(disk) > disk_priority(existing):
            deduplicated[key] = disk

    return list(deduplicated.values())


def disk_priority(disk: dict[str, Any]) -> int:
    candidate_type = str(disk.get("candidate_type") or "unknown")
    type_priority = {
        "usb": 4,
        "removable": 3,
        "standalone": 2,
        "unknown": 1,
    }.get(candidate_type, 0)
    mount_bonus = 1 if disk.get("mount_path") else 0
    return type_priority * 10 + mount_bonus


def build_disk_report(
    device: dict[str, Any],
    udev_props: dict[str, str],
    serial_number: str,
    candidate_type: str,
    detection_reason: str,
) -> dict[str, Any] | None:
    partition_info = derive_partition_info(device)
    model_name = first_value(device.get("model"), udev_props.get("ID_MODEL"))
    display_name = first_value(model_name, serial_number, device_name(device))
    capacity_gb = bytes_to_gb(device.get("size"))

    return {
        "serial_number": serial_number,
        "display_name": display_name,
        "model_name": model_name,
        "capacity_gb": capacity_gb,
        "filesystem_type": partition_info["filesystem_type"],
        "mount_path": partition_info["mount_path"],
        "detection_reason": detection_reason,
        "candidate_type": candidate_type,
        "trusted": False,
        "connected": True,
    }


def derive_partition_info(device: dict[str, Any]) -> dict[str, str | None]:
    partitions = flatten_partitions(device.get("children", []))
    for partition in partitions:
        filesystem_type = partition.get("fstype")
        mount_path = partition.get("mountpoint")
        if filesystem_type or mount_path:
            return {
                "filesystem_type": filesystem_type,
                "mount_path": mount_path,
            }

    return {
        "filesystem_type": device.get("fstype"),
        "mount_path": device.get("mountpoint"),
    }


def flatten_partitions(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for child in children:
        flattened.append(child)
        flattened.extend(flatten_partitions(child.get("children", [])))
    return flattened


def load_udev_properties(name: str) -> dict[str, str]:
    if not name:
        return {}

    try:
        output = run_command(["udevadm", "info", "--query=property", "--name", f"/dev/{name}"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {}

    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value

    return properties


def run_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def mock_disks() -> list[dict[str, Any]]:
    return [
        {
            "serial_number": "AGENT-DISK-001",
            "display_name": "USB Backup Alpha",
            "model_name": "Samsung T7 Shield",
            "capacity_gb": 2000,
            "filesystem_type": "ext4",
            "mount_path": "/mnt/usb-backup-alpha",
            "detection_reason": "mock development candidate",
            "candidate_type": "usb",
            "trusted": False,
            "connected": True,
        },
        {
            "serial_number": "AGENT-DISK-002",
            "display_name": "Standalone Backup Beta",
            "model_name": "WD Red Plus",
            "capacity_gb": 4000,
            "filesystem_type": "xfs",
            "mount_path": "/mnt/backup-beta",
            "detection_reason": "mock standalone candidate",
            "candidate_type": "standalone",
            "trusted": False,
            "connected": True,
        },
    ]


def post_json(settings: AgentSettings, path: str, payload: dict[str, Any]) -> None:
    base_url = settings.api_base_url.rstrip("/")
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(f"{base_url}{path}", json=payload)
        response.raise_for_status()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def device_name(device: dict[str, Any]) -> str:
    return str(device.get("kname") or device.get("name") or "")


def disk_serial_number(device: dict[str, Any], udev_props: dict[str, str]) -> str | None:
    return first_value(
        device.get("serial"),
        udev_props.get("ID_SERIAL_SHORT"),
        udev_props.get("ID_SERIAL"),
    )


def first_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def bytes_to_gb(raw_size: Any) -> int:
    try:
        size_bytes = int(raw_size)
    except (TypeError, ValueError):
        return 0

    if size_bytes <= 0:
        return 0

    return max(1, round(size_bytes / (1024**3)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Proxmox host agent scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("heartbeat", help="Send a heartbeat to the backend")
    subparsers.add_parser("sync-state", help="Send heartbeat, then send a real disk report")
    subparsers.add_parser("report-disks", help="Discover backup candidate disks and send a disk report")
    subparsers.add_parser("report-mock-disks", help="Send a mock disk report for development")
    prepare_parser = subparsers.add_parser(
        "prepare-external-datastore",
        help="Validate mount path and create the target export directory",
    )
    prepare_parser.add_argument("--mount-path", required=True)
    prepare_parser.add_argument("--target-path", required=True)
    export_parser = subparsers.add_parser(
        "run-external-export",
        help="Run or simulate the external PBS export boundary",
    )
    export_parser.add_argument("--target-path", required=True)
    export_parser.add_argument("--datastore-name", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "heartbeat":
        post_heartbeat(settings)
        return

    if args.command == "sync-state":
        sync_state(settings)
        return

    if args.command == "report-disks":
        post_real_disk_report(settings)
        return

    if args.command == "report-mock-disks":
        post_mock_disk_report(settings)
        return

    if args.command == "prepare-external-datastore":
        prepare_external_datastore(args.mount_path, args.target_path)
        return

    if args.command == "run-external-export":
        run_external_export(args.target_path, args.datastore_name)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
