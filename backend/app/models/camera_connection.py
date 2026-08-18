import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CameraConnection(Base):
    """A physical adjacency between two cameras at the same site.

    Hand-drawn by an operator ("these two are joined by a hallway"), never
    inferred. This is the entire basis of journeys: a manually-curated
    adjacency graph plus event timing.

    It is deliberately NOT person re-identification — no appearance
    embeddings, no biometrics, no visual identity matching. A journey is a
    probabilistic correlation ("plausibly the same visitor, given these
    cameras are adjacent and the events are close in time"), and every piece
    of copy built on it must keep saying so.
    """

    __tablename__ = "camera_connections"
    __table_args__ = (
        Index("ix_camera_connections_site", "site_id"),
        # Journey traversal asks "what is adjacent to camera X?" repeatedly,
        # against both ends of the pair.
        Index("ix_camera_connections_a", "camera_a_id"),
        Index("ix_camera_connections_b", "camera_b_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    # Adjacency only makes physical sense within one building, so both
    # cameras must belong to this site.
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False
    )
    # Stored normalised so (A,B) and (B,A) are the same row: camera_a_id is
    # always the lexicographically smaller uuid. That makes the unordered pair
    # dedupable with an ordinary unique index instead of application checks.
    camera_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False
    )
    camera_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
