import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_timestamp", "org_id", text("timestamp DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # low, medium, high, critical
    description: Mapped[str] = mapped_column(Text, nullable=False)
    bounding_boxes: Mapped[list] = mapped_column(JSONB, default=list)

    snapshot_url: Mapped[str] = mapped_column(Text, nullable=False)
    clip_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_model: Mapped[str] = mapped_column(String(50), default="gemini-2.0-flash")
    ai_response_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)  # approved, rejected, reclassified
    feedback_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    feedback_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera = relationship("Camera")
