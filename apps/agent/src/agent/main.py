import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")


@dataclass(frozen=True)
class AgentSettings:
    api_base_url: str = os.getenv("AGENT_API_BASE_URL", "http://localhost:8000/api/v1")
    hostname: str = os.getenv("AGENT_HOSTNAME", os.getenv("COMPUTERNAME", "proxmox-host"))
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


def post_mock_disk_report(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": [
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
        ],
    }
    post_json(settings, "/agent/disks/report", payload)
    logger.info("Mock disk report sent for host %s", settings.hostname)


def post_json(settings: AgentSettings, path: str, payload: dict) -> None:
    base_url = settings.api_base_url.rstrip("/")
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(f"{base_url}{path}", json=payload)
        response.raise_for_status()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Proxmox host agent scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("heartbeat", help="Send a heartbeat to the backend")
    subparsers.add_parser("report-disks", help="Send a mock disk report to the backend")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "heartbeat":
        post_heartbeat(settings)
        return

    if args.command == "report-disks":
        post_mock_disk_report(settings)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
