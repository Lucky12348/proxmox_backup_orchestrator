from datetime import datetime

from pydantic import BaseModel

from app.models import VMType
from app.schemas.base import UTCDateTimeModel


class PBSStatusRead(UTCDateTimeModel):
    connected: bool
    datastore: str
    verify_ssl: bool
    message: str
    last_sync_at: datetime | None = None
    sync_running: bool = False
    last_sync_error: str | None = None


class PBSSyncRead(BaseModel):
    matched_vms: int
    matched_cts: int
    total_snapshots_seen: int
    already_running: bool = False


class PBSInventoryRead(UTCDateTimeModel):
    vm_id: int
    name: str
    vm_type: VMType
    last_backup_at: datetime | None
    protected: bool
