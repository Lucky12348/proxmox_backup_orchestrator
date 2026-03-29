from sqlalchemy import Boolean, Integer, String, Text
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

    assignments = relationship("DiskAssignment", back_populates="disk", cascade="all, delete-orphan")
