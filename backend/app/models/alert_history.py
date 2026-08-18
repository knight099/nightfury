import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AlertHistory(Base):
    __tablename__ = "alert_history"
    __table_args__ = (
        # The escalation sweep asks "which rungs have already fired for this
        # event+rule?" on every pass, so that lookup gets its own index.
        Index("ix_alert_history_event_rule", "event_id", "rule_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_rules.id"), nullable=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent, delivered, failed
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Which escalation rung produced this delivery. NULL = the rule's initial
    # fire. Keeping it here rather than on the event means the ladder holds no
    # state of its own: history IS the record of what was sent, so the sweep
    # cannot drift out of sync with reality or double-send after a restart.
    escalation_rung: Mapped[int | None] = mapped_column(Integer, nullable=True)
