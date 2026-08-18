import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FootfallCount(Base):
    """One heartbeat's worth of line-crossing counts for one camera line.

    Stored as raw buckets rather than a running total: a running total cannot
    be corrected, re-aggregated, or reasoned about after the fact, and a
    duplicated heartbeat would corrupt it permanently.

    These are ESTIMATES. The counter is built on tracking without
    re-identification, so it over-counts on occlusion and under-counts in
    crowds (see ``agent/pipeline/footfall.py``). Anything reading this table
    must present it as a relative trend, never as an absolute visitor count.
    """

    __tablename__ = "footfall_counts"
    __table_args__ = (
        Index("ix_footfall_org_bucket", "org_id", "bucket_at"),
        Index("ix_footfall_camera_bucket", "camera_id", "bucket_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False)

    line_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # End of the interval these counts cover — i.e. when the heartbeat landed.
    bucket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
