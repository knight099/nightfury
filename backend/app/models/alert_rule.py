import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class AlertRule(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL = all sites, preserving the behaviour of every rule that existed
    # before multi-site estates. A multi-site operator otherwise manages one
    # flat rule list with no way to say "this applies to the car park only".
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True
    )

    cameras: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # empty = all
    event_types: Mapped[list] = mapped_column(ARRAY(String), default=list)  # empty = all
    min_severity: Mapped[str] = mapped_column(String(10), default="low")
    time_window: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {start, end, days}
    zones: Mapped[list] = mapped_column(ARRAY(String), default=list)

    notify_channels: Mapped[list] = mapped_column(ARRAY(String), nullable=False)  # whatsapp, email, webhook
    notify_contacts: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{type, value}]
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Ordered escalation rungs, each:
    #   {"after_seconds": int, "channels": [str], "contacts": [{type, value}]}
    # Fired by the sweep in services/alert_escalation.py when an event is
    # STILL unacknowledged after the rung's delay. Empty list = today's
    # behaviour (notify once, never chase), so existing rules are unchanged.
    escalation: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
