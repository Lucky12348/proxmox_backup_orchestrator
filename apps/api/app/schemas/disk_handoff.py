from pydantic import BaseModel, ConfigDict


class DiskHandoffRequest(BaseModel):
    confirmation: bool = False


class DiskHandoffStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    disk_id: int
    serial_number: str
    handoff_status: str
    proxmox_usb_mapping: str | None
    pbs_handoff_slot: str | None
    pbs_visible: bool
    pbs_device_path: str | None
    message: str
