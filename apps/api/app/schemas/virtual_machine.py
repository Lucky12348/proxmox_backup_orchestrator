from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import VMType
from app.schemas.base import UTCDateTimeModel


class VirtualMachineRead(UTCDateTimeModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    vm_type: VMType
    critical: bool
    size_gb: int
    enabled: bool
    source: str
    external_id: str | None
    node_name: str | None
    runtime_status: str | None
    last_seen_at: datetime | None
    last_backup_at: datetime | None
    ignored: bool = False
    ignore_reason: str | None = None


class VirtualMachineUpdate(BaseModel):
    critical: bool | None = None
    enabled: bool | None = None
    size_gb: int | None = Field(default=None, ge=0)
