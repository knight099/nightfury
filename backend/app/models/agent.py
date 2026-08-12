import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("org_id", "machine_id", name="uq_agent_org_machine"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    machine_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pubkey: Mapped[str] = mapped_column(String(512), nullable=False)
    device_token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # Non-secret lookup key for the device token (truncated SHA-256 digest).
    # Lets token auth do one indexed lookup + one Argon2 verify instead of
    # an O(N_agents) scan-and-verify. Nullable for rows paired before this
    # column existed; those are backfilled on next successful auth. See
    # app.services.device_token_service for why this is safe to store.
    device_token_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unpaired"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
