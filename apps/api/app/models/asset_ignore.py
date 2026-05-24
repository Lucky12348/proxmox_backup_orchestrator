from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssetIgnore(Base):
    __tablename__ = "asset_ignores"
    __table_args__ = (
        UniqueConstraint("source", "node", "vmid", name="uq_asset_ignores_source_node_vmid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="proxmox")
    node: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    vmid: Mapped[str] = mapped_column(String(64), nullable=False)
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=datetime.utcnow)
