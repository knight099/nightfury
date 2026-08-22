"""assistant_proposals

Revision ID: 80f8c57dc838
Revises: c9f4e2b71a58
Create Date: 2026-08-22 19:11:01.121244

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '80f8c57dc838'
down_revision: Union[str, None] = 'c9f4e2b71a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('alert_rule','camera_connection')",
            name="ck_assistant_proposals_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','applied','rejected','expired')",
            name="ck_assistant_proposals_status",
        ),
    )
    op.create_index(
        "ix_assistant_proposals_conv",
        "assistant_proposals",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_assistant_proposals_org_status",
        "assistant_proposals",
        ["org_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_proposals_org_status", table_name="assistant_proposals")
    op.drop_index("ix_assistant_proposals_conv", table_name="assistant_proposals")
    op.drop_table("assistant_proposals")
