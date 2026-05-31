import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.system import AutoSyncRead, SystemTimeRead
from app.services.host_agent import HostAgentError, get_host_agent_client, get_pbs_agent_client
from app.services.sync_state import trigger_auto_sync_if_stale


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/time", response_model=SystemTimeRead)
def get_system_time() -> SystemTimeRead:
    now_utc = datetime.now(timezone.utc)
    local = datetime.now().astimezone()
    timezone_name = local.tzname() or str(local.tzinfo) or "local"

    return SystemTimeRead(
        now_utc=now_utc,
        now_local=local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        timezone=timezone_name,
        hostname=socket.gethostname(),
    )


@router.post("/auto-sync", response_model=AutoSyncRead)
def trigger_auto_sync() -> AutoSyncRead:
    result = trigger_auto_sync_if_stale(get_settings())
    return AutoSyncRead(
        enabled=bool(result["enabled"]),
        proxmox_triggered=bool(result["proxmox_triggered"]),
        pbs_triggered=bool(result["pbs_triggered"]),
    )


@router.get("/version")
def get_system_version() -> dict[str, object]:
    settings = get_settings()
    return {
        "api": {
            "component": "api",
            "package_version": "0.1.0",
            "git_sha": _git_sha(),
            "started_at": None,
            "installed_path": str(Path(__file__).resolve()),
            "python_executable": sys.executable,
            "capabilities": ["version-endpoint"],
        },
        "proxmox_agent": _agent_version_payload(get_host_agent_client()),
        "pbs_agent": _agent_version_payload(get_pbs_agent_client()),
        "web": {
            "component": "web",
            "git_sha": _git_sha(),
            "package_version": "0.1.0",
            "installed_path": settings.frontend_origin,
            "capabilities": [],
        },
    }


def _agent_version_payload(client) -> dict[str, object]:
    try:
        return client.get_version()
    except HostAgentError as exc:
        return {"ok": False, "message": str(exc), "capabilities": []}


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None
