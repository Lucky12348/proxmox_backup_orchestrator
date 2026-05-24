from pydantic import BaseModel


class NotificationStatusRead(BaseModel):
    enabled: bool
    provider: str
    configured: bool
    base_url: str | None
    topic: str | None
    username: str | None
    events: dict[str, bool]
    low_coverage_threshold_percent: float


class NotificationTestRead(BaseModel):
    sent: bool
    message: str
