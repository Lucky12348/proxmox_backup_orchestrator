from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.backup_run import BackupRunStatus


class DiskPreparationMode(str, Enum):
    PRESERVE_EXISTING_DATA = "preserve_existing_data"
    DEDICATED_BACKUP = "dedicated_backup"


class DiskPreparationRun(Base):
    __tablename__ = "disk_preparation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("external_disks.id"), nullable=False)
    mode: Mapped[DiskPreparationMode] = mapped_column(
        SqlEnum(DiskPreparationMode, name="disk_preparation_mode", native_enum=False),
        nullable=False,
    )
    status: Mapped[BackupRunStatus] = mapped_column(
        SqlEnum(BackupRunStatus, name="disk_preparation_status", native_enum=False),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    message: Mapped[str | None] = mapped_column(Text)
    mount_path: Mapped[str | None] = mapped_column(String(512))
    filesystem_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
