from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationPreferences(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    notifications_enabled_override: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    notify_on_backup_success: Mapped[bool] = mapped_column(default=True)
    notify_on_backup_failure: Mapped[bool] = mapped_column(default=True)
    notify_on_disk_eject_ready: Mapped[bool] = mapped_column(default=True)
    notify_on_update_result: Mapped[bool] = mapped_column(default=True)
    notify_on_agent_degraded: Mapped[bool] = mapped_column(default=True)
    notify_on_low_coverage: Mapped[bool] = mapped_column(default=True)
    notify_on_disk_new_detected: Mapped[bool] = mapped_column(default=True)
    notify_on_disk_known_detected: Mapped[bool] = mapped_column(default=True)
    notify_on_planned_disk_detected: Mapped[bool] = mapped_column(default=True)
    notify_on_planned_backup_reminder: Mapped[bool] = mapped_column(default=True)
    notify_on_planned_backup_started: Mapped[bool] = mapped_column(default=True)
    notify_on_planned_confirmation_required: Mapped[bool] = mapped_column(default=True)
    notify_on_planned_backup_missed: Mapped[bool] = mapped_column(default=True)
    low_coverage_threshold_percent: Mapped[float] = mapped_column(default=100)
    disk_detection_notify_cooldown_seconds: Mapped[int] = mapped_column(default=1800)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
