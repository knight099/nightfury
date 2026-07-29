"""soft_delete_columns

Revision ID: e7b3f9a2c5d1
Revises: d4a9c2e8f1b6
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3f9a2c5d1"
down_revision: Union[str, None] = "d4a9c2e8f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["organizations", "users", "sites", "cameras", "alert_rules"]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "deleted_at")
