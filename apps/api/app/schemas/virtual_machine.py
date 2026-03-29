from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import VMType


class VirtualMachineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    vm_type: VMType
    critical: bool
    size_gb: int
    enabled: bool
    last_backup_at: datetime | None


class VirtualMachineUpdate(BaseModel):
    critical: bool | None = None
    enabled: bool | None = None
    size_gb: int | None = Field(default=None, ge=0)
