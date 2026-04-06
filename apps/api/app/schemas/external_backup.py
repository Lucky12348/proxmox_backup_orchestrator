from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import BackupRunStatus, ExternalBackupMode


class ExternalBackupRunRequest(BaseModel):
    disk_id: int = Field(gt=0)
    confirmation: bool = False


class ExternalBackupRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    disk_id: int
    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    target_path: str
    datastore_name: str
    message: str | None
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str | None
    return_code: int | None
    mode: ExternalBackupMode
    created_at: datetime


class ExternalBackupRunSummaryRead(BaseModel):
    id: int
    disk_id: int
    disk_name: str
    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    target_path: str
    datastore_name: str
    message: str | None
    stdout_log: str | None
    stderr_log: str | None
    command_summary: str | None
    return_code: int | None
    mode: ExternalBackupMode
    created_at: datetime
