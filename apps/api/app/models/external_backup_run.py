from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.backup_run import BackupRunStatus


class ExternalBackupMode(str, Enum):
    DEDICATED = "dedicated"
    COEXISTENCE = "coexistence"


class ExternalBackupRun(Base):
    __tablename__ = "external_backup_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("external_disks.id"), nullable=False)
    status: Mapped[BackupRunStatus] = mapped_column(
        SqlEnum(BackupRunStatus, name="external_backup_run_status", native_enum=False),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    target_path: Mapped[str] = mapped_column(String(512), nullable=False)
    datastore_name: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    stdout_log: Mapped[str | None] = mapped_column(Text)
    stderr_log: Mapped[str | None] = mapped_column(Text)
    command_summary: Mapped[str | None] = mapped_column(Text)
    execution_cwd: Mapped[str | None] = mapped_column(String(512))
    return_code: Mapped[int | None]
    current_step: Mapped[str | None] = mapped_column(String(128))
    progress_message: Mapped[str | None] = mapped_column(Text)
    last_log_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    progress_percent: Mapped[float | None] = mapped_column(Float)
    total_groups: Mapped[int | None] = mapped_column(Integer)
    completed_groups: Mapped[int | None] = mapped_column(Integer)
    current_group: Mapped[str | None] = mapped_column(String(255))
    current_snapshot: Mapped[str | None] = mapped_column(String(255))
    current_archive: Mapped[str | None] = mapped_column(String(255))
    downloaded_bytes: Mapped[int | None] = mapped_column(BigInteger)
    current_speed: Mapped[str | None] = mapped_column(String(64))
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    warning_messages: Mapped[list[str] | None] = mapped_column(JSON)
    failed_groups: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    pbs_sync_job_id: Mapped[str | None] = mapped_column(String(255))
    pbs_remote_id: Mapped[str | None] = mapped_column(String(255))
    pbs_task_upid: Mapped[str | None] = mapped_column(Text)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
    auto_eject_after_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[ExternalBackupMode] = mapped_column(
        SqlEnum(ExternalBackupMode, name="external_backup_mode", native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
