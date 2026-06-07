from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import UTCDateTimeModel


class ExternalDiskRead(UTCDateTimeModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    serial_number: str
    reported_serial_number: str | None
    reported_display_name: str | None
    reported_model_name: str | None
    reported_mount_path: str | None
    canonical_serial_number: str | None
    serial_aliases: list[str] | None
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
    filesystem_total_gb: int | None
    filesystem_used_gb: int | None
    filesystem_free_gb: int | None
    last_seen_at: datetime | None
    detection_reason: str | None
    candidate_type: str | None
    trusted: bool
    usable_capacity_gb: int | None
    reserved_capacity_gb: int
    planning_notes: str | None
    source: str
    active: bool
    handoff_status: str | None
    proxmox_usb_mapping: str | None
    pbs_handoff_slot: str | None
    pbs_visible: bool
    pbs_device_path: str | None
    pbs_datastore_name: str | None
    pbs_mount_path: str | None
    pbs_filesystem_type: str | None
    prepared_as_pbs_datastore: bool


class ExternalDiskUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    dedicated_backup_disk: bool | None = None
    allow_existing_data: bool | None = None
    trusted: bool | None = None
    usable_capacity_gb: int | None = Field(default=None, ge=0)
    reserved_capacity_gb: int | None = Field(default=None, ge=0)
    planning_notes: str | None = None
    preferred_root_path: str | None = Field(default=None, max_length=255)
    notes: str | None = None
