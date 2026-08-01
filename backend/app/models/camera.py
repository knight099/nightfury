import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Camera(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    ingest_mode: Mapped[str] = mapped_column(String(20), nullable=False)  # rtsp_pull, rtmp_push, srt_push
    rtsp_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stream_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    enabled_events: Mapped[list] = mapped_column(ARRAY(String), default=list)
    detection_zones: Mapped[list] = mapped_column(JSONB, default=list)
    step_sequence: Mapped[list] = mapped_column(JSONB, default=list)
    reid_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sensitivity: Mapped[str] = mapped_column(String(10), default="medium")  # low, medium, high

    status: Mapped[str] = mapped_column(String(20), default="offline")  # online, offline, error
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    idle_fps: Mapped[float] = mapped_column(Float, default=1.0)
    active_fps: Mapped[float] = mapped_column(Float, default=5.0)

    organization = relationship("Organization", back_populates="cameras")
    site = relationship("Site", back_populates="cameras")
