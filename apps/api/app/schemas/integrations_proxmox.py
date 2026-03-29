from pydantic import BaseModel

from app.schemas.virtual_machine import VirtualMachineRead


class ProxmoxStatusRead(BaseModel):
    connected: bool
    node_name: str
    verify_ssl: bool
    message: str


class ProxmoxSyncRead(BaseModel):
    synced_vms_count: int
    synced_cts_count: int
    total_seen: int
