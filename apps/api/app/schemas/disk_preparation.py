from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import BackupRunStatus, DiskPreparationMode


class DiskPreparationRequest(BaseModel):
    mode: DiskPreparationMode
    mount_base_path: str | None = Field(default=None, max_length=255)
    confirm_destructive: bool = False


class DiskPreparationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    disk_id: int
    mode: DiskPreparationMode
    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    message: str | None
    mount_path: str | None
    filesystem_type: str | None
    created_at: datetime
