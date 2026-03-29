from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentHeartbeatCreate(BaseModel):
    hostname: str = Field(max_length=255)
    agent_version: str = Field(max_length=64)
    observed_at: datetime


class AgentDiskReportItem(BaseModel):
    serial_number: str = Field(max_length=255)
    display_name: str = Field(max_length=255)
    model_name: str | None = Field(default=None, max_length=255)
    capacity_gb: int = Field(ge=0)
    filesystem_type: str | None = Field(default=None, max_length=64)
    mount_path: str | None = Field(default=None, max_length=255)
    detection_reason: str | None = Field(default=None, max_length=255)
    candidate_type: str | None = Field(default=None, max_length=64)
    trusted: bool = False
    connected: bool


class AgentDiskReportCreate(BaseModel):
    hostname: str = Field(max_length=255)
    observed_at: datetime
    disks: list[AgentDiskReportItem]


class AgentHeartbeatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hostname: str
    agent_version: str
    observed_at: datetime


class AgentStatusRead(BaseModel):
    connected: bool
    hostname: str | None
    last_heartbeat_at: datetime | None
    last_report_at: datetime | None
    status: str
    stale_after_minutes: int
    last_seen_age_seconds: int | None
