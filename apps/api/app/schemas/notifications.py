from datetime import datetime

from pydantic import BaseModel, Field


class NotificationStatusRead(BaseModel):
    enabled: bool
    provider: str
    configured: bool
    base_url: str | None
    topic: str | None
    username: str | None
    events: dict[str, bool]
    low_coverage_threshold_percent: float
    environment_enabled: bool = True
    preferences_enabled: bool | None = None
    disk_detection_notify_cooldown_seconds: int = 1800
    sources: dict[str, str] = Field(default_factory=dict)


class NotificationPreferencesRead(BaseModel):
    notifications_enabled_override: bool | None
    notify_on_backup_success: bool
    notify_on_backup_failure: bool
    notify_on_disk_eject_ready: bool
    notify_on_update_result: bool
    notify_on_agent_degraded: bool
    notify_on_low_coverage: bool
    notify_on_disk_new_detected: bool
    notify_on_disk_known_detected: bool
    notify_on_planned_disk_detected: bool
    notify_on_planned_backup_reminder: bool
    notify_on_planned_backup_started: bool
    notify_on_planned_confirmation_required: bool
    notify_on_planned_backup_missed: bool
    low_coverage_threshold_percent: float
    disk_detection_notify_cooldown_seconds: int
    updated_at: datetime | None = None
    source: str = "environment/server value"


class NotificationPreferencesUpdate(BaseModel):
    notifications_enabled_override: bool | None = None
    notify_on_backup_success: bool | None = None
    notify_on_backup_failure: bool | None = None
    notify_on_disk_eject_ready: bool | None = None
    notify_on_update_result: bool | None = None
    notify_on_agent_degraded: bool | None = None
    notify_on_low_coverage: bool | None = None
    notify_on_disk_new_detected: bool | None = None
    notify_on_disk_known_detected: bool | None = None
    notify_on_planned_disk_detected: bool | None = None
    notify_on_planned_backup_reminder: bool | None = None
    notify_on_planned_backup_started: bool | None = None
    notify_on_planned_confirmation_required: bool | None = None
    notify_on_planned_backup_missed: bool | None = None
    low_coverage_threshold_percent: float | None = Field(default=None, ge=0, le=100)
    disk_detection_notify_cooldown_seconds: int | None = Field(default=None, ge=0)


class NotificationTestRead(BaseModel):
    sent: bool
    message: str
