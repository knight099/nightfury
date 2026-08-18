import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
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

    # ─── Capacity & placement ──────────────────────────────────────────────
    # An agent is physically on one LAN, so it can only serve cameras at the
    # site it sits in. Nullable for agents paired before this column existed;
    # backfilled from their cameras and set on first camera registration.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True, index=True
    )
    # How many cameras this box says it can run. Reported by the agent, not
    # configured centrally — see agent/pipeline/capacity.py. NULL means the
    # agent has not reported yet; placement treats that as the conservative
    # default rather than as "unlimited".
    capacity_cameras: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "declared" = derived from CPU/RAM at startup; "measured" = revised from
    # observed per-camera analysis cost. Surfaced in the fleet view so an
    # operator knows how much to trust the number.
    capacity_source: Mapped[str] = mapped_column(String(16), nullable=False, default="declared")
    # Denormalised count of cameras placed here, maintained by the placement
    # reconciler so placement decisions don't need a COUNT per agent.
    assigned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Bumped whenever this agent's assignment set changes. Serves as the ETag
    # for GET /internal/assignments so unchanged config isn't re-transferred.
    assignment_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Agent-reported degradation ("ok" | "degraded" | "over_capacity") with a
    # human-readable reason. Set from the heartbeat; shown in the fleet view.
    load_state: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    load_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unpaired"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
