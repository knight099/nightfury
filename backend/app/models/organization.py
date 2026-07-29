import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(20), default="starter")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    whatsapp_alert_contacts: Mapped[list] = mapped_column(JSONB, default=list)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    # No delete-orphan cascade: deletion is soft (see api/admin.py), and this
    # relationship cascade previously turned one db.delete(org) into wiping
    # every user/site/camera underneath it.
    users = relationship("User", back_populates="organization")
    sites = relationship("Site", back_populates="organization")
    cameras = relationship("Camera", back_populates="organization")
