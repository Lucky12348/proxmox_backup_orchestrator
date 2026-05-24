from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AssetIgnoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    node: str
    vmid: str
    ignored: bool
    reason: str | None
    updated_at: datetime


class AssetIgnoreUpdate(BaseModel):
    ignored: bool
    reason: str | None = None
