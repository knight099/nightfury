"""audit_log_method_widen

Widen audit_log.method from VARCHAR(10) to VARCHAR(20) — the impersonate
route writes method="IMPERSONATE" (11 chars), which doesn't fit in the
original VARCHAR(10) column and fails with StringDataRightTruncationError.

Revision ID: a3f6d1c9e8b4
Revises: 7cfcfc949409
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f6d1c9e8b4'
down_revision: Union[str, None] = '7cfcfc949409'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "audit_log",
        "method",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_log",
        "method",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
