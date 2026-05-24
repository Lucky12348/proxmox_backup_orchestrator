from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduledBackupRecurrenceType(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduledBackupStartMode(str, Enum):
    AUTO_ON_DISK_DETECTED = "auto_on_disk_detected"
    MANUAL_CONFIRMATION = "manual_confirmation"


class ScheduledBackupRunStatus(str, Enum):
    PENDING = "pending"
    WAITING_FOR_DISK = "waiting_for_disk"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    MISSED = "missed"
    CANCELLED = "cancelled"


class ScheduledBackupEvent(Base):
    __tablename__ = "scheduled_backup_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disk_serial: Mapped[str] = mapped_column(String(255), nullable=False)
    disk_label_or_model: Mapped[str | None] = mapped_column(String(255))
    datastore: Mapped[str] = mapped_column(String(255), nullable=False)
    recurrence_type: Mapped[ScheduledBackupRecurrenceType] = mapped_column(
        SqlEnum(ScheduledBackupRecurrenceType, name="scheduled_backup_recurrence_type", native_enum=False),
        nullable=False,
    )
    recurrence_config: Mapped[dict | None] = mapped_column(JSON)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Paris")
    window_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    window_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    notify_before_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    start_mode: Mapped[ScheduledBackupStartMode] = mapped_column(
        SqlEnum(ScheduledBackupStartMode, name="scheduled_backup_start_mode", native_enum=False),
        nullable=False,
    )
    auto_eject_after_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class ScheduledBackupRun(Base):
    __tablename__ = "scheduled_backup_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("scheduled_backup_events.id"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    window_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[ScheduledBackupRunStatus] = mapped_column(
        SqlEnum(ScheduledBackupRunStatus, name="scheduled_backup_run_status", native_enum=False),
        nullable=False,
    )
    disk_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    backup_run_id: Mapped[int | None] = mapped_column(ForeignKey("external_backup_runs.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
