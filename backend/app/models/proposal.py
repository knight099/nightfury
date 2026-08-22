import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Proposal(Base):
    """A configuration change the assistant has prepared for a human to confirm.

    Persisted rather than held in the response for two reasons. Audit: "who
    changed this alert rule and why" needs an answer, and "the assistant
    proposed it in this conversation, Priya applied it at 14:32" is that
    answer. Durability: a pending proposal survives a page refresh.

    `summary` is templated server-side from `payload` and is never written by
    the model — if the model wrote the card text, the text and the payload
    could disagree, and the user would be confirming a sentence while the
    system executed a different change.
    """

    __tablename__ = "assistant_proposals"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('alert_rule','camera_connection')",
            name="ck_assistant_proposals_kind",
        ),
        CheckConstraint(
            "status IN ('pending','applied','rejected','expired')",
            name="ck_assistant_proposals_status",
        ),
        Index("ix_assistant_proposals_conv", "conversation_id", "created_at"),
        Index("ix_assistant_proposals_org_status", "org_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Matches chat_messages.conversation_id, which is a bare indexed column —
    # there is no conversations table — so no foreign key here either.
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
