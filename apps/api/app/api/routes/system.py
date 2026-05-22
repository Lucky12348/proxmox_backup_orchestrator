import socket
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.system import AutoSyncRead, SystemTimeRead
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
