from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, Text
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
    mode: Mapped[ExternalBackupMode] = mapped_column(
        SqlEnum(ExternalBackupMode, name="external_backup_mode", native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
