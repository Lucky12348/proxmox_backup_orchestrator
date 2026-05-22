from datetime import datetime

from pydantic import ConfigDict

from app.models import BackupRunStatus
from app.schemas.base import UTCDateTimeModel


class BackupRunRead(UTCDateTimeModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    triggered_by: str
    summary: str | None
