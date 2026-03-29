from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VMType(str, Enum):
    VM = "vm"
    CT = "ct"


class VirtualMachine(Base):
    __tablename__ = "virtual_machines"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_virtual_machines_source_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vm_type: Mapped[VMType] = mapped_column(
        SqlEnum(VMType, name="vm_type", native_enum=False),
        nullable=False,
    )
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    size_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="seed")
    external_id: Mapped[str | None] = mapped_column(String(64))
    node_name: Mapped[str | None] = mapped_column(String(255))
    runtime_status: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    assignments = relationship("DiskAssignment", back_populates="vm", cascade="all, delete-orphan")
