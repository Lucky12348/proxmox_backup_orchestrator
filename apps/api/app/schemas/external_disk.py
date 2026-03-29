from pydantic import BaseModel, ConfigDict, Field


class ExternalDiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    serial_number: str
    display_name: str
    capacity_gb: int
    connected: bool
    dedicated_backup_disk: bool
    allow_existing_data: bool
    preferred_root_path: str | None
    notes: str | None


class ExternalDiskUpdate(BaseModel):
    dedicated_backup_disk: bool | None = None
    allow_existing_data: bool | None = None
    preferred_root_path: str | None = Field(default=None, max_length=255)
    notes: str | None = None
