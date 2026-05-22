from datetime import datetime

from pydantic import BaseModel


class SystemTimeRead(BaseModel):
    now_utc: datetime
    now_local: str
    timezone: str
    hostname: str


class AutoSyncRead(BaseModel):
    enabled: bool
    proxmox_triggered: bool
    pbs_triggered: bool
