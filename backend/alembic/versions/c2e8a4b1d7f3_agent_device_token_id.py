"""agents.device_token_id lookup key

Adds a non-secret lookup key (truncated SHA-256 of the device token) so
device-token authentication can do one indexed lookup + one Argon2 verify
instead of scanning every agent row and Argon2-verifying against each hash.

Nullable on purpose: rows paired before this column existed keep NULL and
are matched by the legacy scan path, which backfills this column on the next
successful authentication (see app/services/agent_auth.py).

Revision ID: c2e8a4b1d7f3
Revises: a6d8b2f4e9c1
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e8a4b1d7f3"
down_revision: Union[str, None] = "a6d8b2f4e9c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("device_token_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_agents_device_token_id", "agents", ["device_token_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_agents_device_token_id", table_name="agents")
    op.drop_column("agents", "device_token_id")
