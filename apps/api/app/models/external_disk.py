from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExternalDisk(Base):
    __tablename__ = "external_disks"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dedicated_backup_disk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_existing_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preferred_root_path: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    filesystem_type: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(255))
    mount_path: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    detection_reason: Mapped[str | None] = mapped_column(String(255))
    candidate_type: Mapped[str | None] = mapped_column(String(64))
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usable_capacity_gb: Mapped[int | None] = mapped_column(Integer)
    reserved_capacity_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planning_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="seed")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assignments = relationship("DiskAssignment", back_populates="disk", cascade="all, delete-orphan")
