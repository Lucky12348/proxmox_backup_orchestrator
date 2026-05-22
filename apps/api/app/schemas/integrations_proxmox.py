from pydantic import BaseModel
from datetime import datetime

from app.schemas.virtual_machine import VirtualMachineRead


class ProxmoxStatusRead(BaseModel):
    connected: bool
    node_name: str
    verify_ssl: bool
    message: str
    last_sync_at: datetime | None = None
    sync_running: bool = False
    last_sync_error: str | None = None


class ProxmoxSyncRead(BaseModel):
    synced_vms_count: int
    synced_cts_count: int
    total_seen: int
    already_running: bool = False
