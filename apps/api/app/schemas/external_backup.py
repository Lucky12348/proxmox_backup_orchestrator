from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import BackupRunStatus, ExternalBackupMode
from app.schemas.base import UTCDateTimeModel


class ExternalBackupRunRequest(BaseModel):
    disk_id: int = Field(gt=0)
    confirmation: bool = False


class ExternalBackupRunRead(UTCDateTimeModel):
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
    execution_cwd: str | None
    return_code: int | None
    current_step: str | None
    progress_message: str | None
    last_log_at: datetime | None
    progress_percent: float | None
    total_groups: int | None
    completed_groups: int | None
    current_group: str | None
    current_snapshot: str | None
    current_archive: str | None
    downloaded_bytes: int | None
    current_speed: str | None
    last_progress_at: datetime | None
    warning_messages: list[str] | None
    failed_groups: list[dict[str, str]] | None
    pbs_sync_job_id: str | None
    pbs_remote_id: str | None
    pbs_task_upid: str | None
    elapsed_seconds: int | None
    mode: ExternalBackupMode
    created_at: datetime


class ExternalBackupRunSummaryRead(UTCDateTimeModel):
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
    execution_cwd: str | None
    return_code: int | None
    current_step: str | None
    progress_message: str | None
    last_log_at: datetime | None
    progress_percent: float | None
    total_groups: int | None
    completed_groups: int | None
    current_group: str | None
    current_snapshot: str | None
    current_archive: str | None
    downloaded_bytes: int | None
    current_speed: str | None
    last_progress_at: datetime | None
    warning_messages: list[str] | None
    failed_groups: list[dict[str, str]] | None
    pbs_sync_job_id: str | None
    pbs_remote_id: str | None
    pbs_task_upid: str | None
    elapsed_seconds: int | None
    mode: ExternalBackupMode
    created_at: datetime


class ExternalBackupRunLogRequest(BaseModel):
    step: str | None = Field(default=None, max_length=128)
    message: str | None = None
    stdout_line: str | None = None
    stderr_line: str | None = None
    command: str | None = None
