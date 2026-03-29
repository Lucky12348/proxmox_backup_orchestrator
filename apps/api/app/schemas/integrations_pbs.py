from datetime import datetime

from pydantic import BaseModel

from app.models import VMType


class PBSStatusRead(BaseModel):
    connected: bool
    datastore: str
    verify_ssl: bool
    message: str


class PBSSyncRead(BaseModel):
    matched_vms: int
    matched_cts: int
    total_snapshots_seen: int


class PBSInventoryRead(BaseModel):
    vm_id: int
    name: str
    vm_type: VMType
    last_backup_at: datetime | None
    protected: bool
