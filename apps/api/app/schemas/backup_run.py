from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import BackupRunStatus


class BackupRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    triggered_by: str
    summary: str | None
