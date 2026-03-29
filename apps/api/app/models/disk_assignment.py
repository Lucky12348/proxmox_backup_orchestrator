from sqlalchemy import Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DiskAssignment(Base):
    __tablename__ = "disk_assignments"
    __table_args__ = (UniqueConstraint("disk_id", "vm_id", name="uq_disk_assignment_disk_vm"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disk_id: Mapped[int] = mapped_column(ForeignKey("external_disks.id", ondelete="CASCADE"), nullable=False)
    vm_id: Mapped[int] = mapped_column(ForeignKey("virtual_machines.id", ondelete="CASCADE"), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    disk = relationship("ExternalDisk", back_populates="assignments")
    vm = relationship("VirtualMachine", back_populates="assignments")
