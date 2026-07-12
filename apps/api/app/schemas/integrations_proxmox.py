from pydantic import BaseModel, Field
from datetime import datetime

from app.schemas.base import UTCDateTimeModel
from app.schemas.virtual_machine import VirtualMachineRead


class ProxmoxStatusRead(UTCDateTimeModel):
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


class ProxmoxBackupJobAssetRead(BaseModel):
    vmid: int
    name: str
    vm_type: str
    node: str | None = None
    included: bool
    ignored: bool = False


class ProxmoxBackupJobRead(BaseModel):
    job_id: str
    enabled: bool
    node: str | None
    schedule: str | None
    storage: str | None
    retention: str | None
    selection_mode: str
    selected_vmids: list[int]
    comment: str | None
    next_run: str | None = None
    supported: bool
    unsupported_reason: str | None = None
    included_assets: list[ProxmoxBackupJobAssetRead] = Field(default_factory=list)
    available_assets: list[ProxmoxBackupJobAssetRead] = Field(default_factory=list)


class ProxmoxBackupJobSelectionUpdate(BaseModel):
    selected_vmids: list[int]


class ProxmoxBackupJobUpsert(BaseModel):
    """Request body for both creating a new job (POST) and replacing an
    existing one's core fields (PUT). Deliberately covers only the fields an
    operator sets day-to-day (node, storage, schedule, VM selection, a simple
    keep-* retention) — not the full Proxmox editor (notifications, note
    template, advanced). Use the Proxmox UI directly for those."""

    storage: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    node: str | None = None
    selected_vmids: list[int] = Field(default_factory=list)
    mode: str = "snapshot"
    enabled: bool = True
    comment: str | None = None
    keep_last: int | None = Field(default=None, ge=0)
    keep_daily: int | None = Field(default=None, ge=0)
    keep_weekly: int | None = Field(default=None, ge=0)
    keep_monthly: int | None = Field(default=None, ge=0)
    keep_yearly: int | None = Field(default=None, ge=0)
