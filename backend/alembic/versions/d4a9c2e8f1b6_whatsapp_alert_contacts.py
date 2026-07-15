"""whatsapp_alert_contacts

Revision ID: d4a9c2e8f1b6
Revises: b7e2f1a3c9d5
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a9c2e8f1b6"
down_revision: Union[str, None] = "b7e2f1a3c9d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "whatsapp_alert_contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "whatsapp_alert_contacts")
