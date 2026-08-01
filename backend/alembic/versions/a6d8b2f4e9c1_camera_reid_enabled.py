"""camera_reid_enabled

Revision ID: a6d8b2f4e9c1
Revises: f1a9c3e7b5d2
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6d8b2f4e9c1"
down_revision: Union[str, None] = "f1a9c3e7b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("reid_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("cameras", "reid_enabled")
