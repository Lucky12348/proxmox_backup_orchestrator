from datetime import datetime

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
    filesystem_type: str | None
    model_name: str | None
    mount_path: str | None
    last_seen_at: datetime | None
    detection_reason: str | None
    candidate_type: str | None
    trusted: bool
    source: str
    active: bool


class ExternalDiskUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    dedicated_backup_disk: bool | None = None
    allow_existing_data: bool | None = None
    trusted: bool | None = None
    preferred_root_path: str | None = Field(default=None, max_length=255)
    notes: str | None = None
