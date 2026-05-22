from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import UTCDateTimeModel


class MaintenanceCommandResultRead(BaseModel):
    command: str
    stdout: str | None
    stderr: str | None
    return_code: int


class MaintenanceComponentStatusRead(BaseModel):
    component: str
    branch: str | None
    local_commit: str | None
    remote_commit: str | None
    status: str
    error: str | None = None
    logs: list[MaintenanceCommandResultRead] = Field(default_factory=list)


class MaintenanceActionRead(UTCDateTimeModel):
    component: str
    status: MaintenanceComponentStatusRead
    logs: list[MaintenanceCommandResultRead]
    action_status: str
    finished_at: datetime | None = None


class MaintenanceStatusRead(BaseModel):
    components: list[MaintenanceComponentStatusRead]
