from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExternalDisk(Base):
    __tablename__ = "external_disks"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    reported_serial_number: Mapped[str | None] = mapped_column(String(255))
    reported_display_name: Mapped[str | None] = mapped_column(String(255))
    reported_model_name: Mapped[str | None] = mapped_column(String(255))
    reported_mount_path: Mapped[str | None] = mapped_column(String(255))
    canonical_serial_number: Mapped[str | None] = mapped_column(String(255), index=True)
    serial_aliases: Mapped[list[str] | None] = mapped_column(JSON)
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
    filesystem_total_gb: Mapped[int | None] = mapped_column(Integer)
    filesystem_used_gb: Mapped[int | None] = mapped_column(Integer)
    filesystem_free_gb: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    detection_reason: Mapped[str | None] = mapped_column(String(255))
    candidate_type: Mapped[str | None] = mapped_column(String(64))
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usable_capacity_gb: Mapped[int | None] = mapped_column(Integer)
    reserved_capacity_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planning_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="seed")
    reported_by_hostname: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    handoff_status: Mapped[str | None] = mapped_column(String(32))
    proxmox_usb_mapping: Mapped[str | None] = mapped_column(String(255))
    pbs_handoff_slot: Mapped[str | None] = mapped_column(String(32))
    pbs_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pbs_device_path: Mapped[str | None] = mapped_column(String(255))
    pbs_datastore_name: Mapped[str | None] = mapped_column(String(255))
    pbs_mount_path: Mapped[str | None] = mapped_column(String(512))
    pbs_filesystem_type: Mapped[str | None] = mapped_column(String(64))
    prepared_as_pbs_datastore: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    presence_state: Mapped[str] = mapped_column(String(16), nullable=False, default="absent")
    last_detection_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    assignments = relationship("DiskAssignment", back_populates="disk", cascade="all, delete-orphan")
