import argparse
import json
import logging
import os
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")

EXCLUDED_DEVICE_PREFIXES = ("loop", "dm-", "zd", "sr")


@dataclass(frozen=True)
class AgentSettings:
    api_base_url: str = os.getenv("AGENT_API_BASE_URL", "http://localhost:8000/api/v1")
    hostname: str = os.getenv("AGENT_HOSTNAME", socket.gethostname())
    agent_version: str = os.getenv("AGENT_VERSION", "0.1.0")
    timeout_seconds: float = float(os.getenv("AGENT_TIMEOUT_SECONDS", "10"))


def post_heartbeat(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "agent_version": settings.agent_version,
        "observed_at": current_timestamp(),
    }
    post_json(settings, "/agent/heartbeat", payload)
    logger.info("Heartbeat sent for host %s", settings.hostname)


def post_real_disk_report(settings: AgentSettings) -> None:
    disks = discover_real_disks()
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


def discover_real_disks() -> list[dict[str, Any]]:
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
        if not appears_external(device, udev_props):
            continue

        disk_report = build_disk_report(device, udev_props)
        if disk_report:
            discovered.append(disk_report)

    return discovered


def is_candidate_disk(device: dict[str, Any]) -> bool:
    name = device_name(device)
    if device.get("type") != "disk":
        return False

    return not any(name.startswith(prefix) for prefix in EXCLUDED_DEVICE_PREFIXES)


def appears_external(device: dict[str, Any], udev_props: dict[str, str]) -> bool:
    # Keep the first filter pragmatic: only report devices that look removable/external.
    transport = (device.get("tran") or "").lower()
    removable = str(device.get("rm", "0")) == "1"
    hotplug = str(device.get("hotplug", "0")) == "1"
    udev_bus = udev_props.get("ID_BUS", "").lower()
    devpath = udev_props.get("DEVPATH", "").lower()

    return any(
        [
            transport == "usb",
            removable,
            hotplug,
            udev_bus == "usb",
            "usb" in devpath,
            "ID_USB_DRIVER" in udev_props,
        ]
    )


def build_disk_report(device: dict[str, Any], udev_props: dict[str, str]) -> dict[str, Any] | None:
    serial_number = first_value(
        device.get("serial"),
        udev_props.get("ID_SERIAL_SHORT"),
        udev_props.get("ID_SERIAL"),
    )
    if not serial_number:
        return None

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
            "connected": True,
        },
        {
            "serial_number": "AGENT-DISK-002",
            "display_name": "USB Backup Beta",
            "model_name": "WD Elements",
            "capacity_gb": 4000,
            "filesystem_type": "exfat",
            "mount_path": None,
            "connected": False,
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
    subparsers.add_parser("report-disks", help="Discover real disks and send a disk report")
    subparsers.add_parser("report-mock-disks", help="Send a mock disk report for development")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "heartbeat":
        post_heartbeat(settings)
        return

    if args.command == "report-disks":
        post_real_disk_report(settings)
        return

    if args.command == "report-mock-disks":
        post_mock_disk_report(settings)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
