"""device_provisions

Revision ID: b7e2f1a3c9d5
Revises: 6915a91eee84
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2f1a3c9d5"
down_revision: Union[str, None] = "6915a91eee84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_provisions",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("pubkey", sa.String(512), nullable=False),
        sa.Column("machine_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="waiting"),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column("device_token", sa.String(256), nullable=True),
        sa.Column("relay_url", sa.String(256), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_device_provisions_code",
        "device_provisions",
        ["code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_device_provisions_code", table_name="device_provisions")
    op.drop_table("device_provisions")
