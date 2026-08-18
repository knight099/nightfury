"""digests.site_id — per-site digests

Revision ID: e6f1b8d40a37
Revises: d5e9a3c07f26
Create Date: 2026-08-18

NULL means an organisation-wide digest, which is what every existing row is
and what the scheduled morning/evening runs still produce. A non-NULL value
means the digest covers one site only.

This exists because enforcing `users.sites_access` left site-restricted
accounts with NO digest at all: a digest computed over every event in the org
cannot be narrowed to one site after the fact, so the read path had to deny
rather than leak. Recording the scope at generation time is what makes a
digest safely readable by a scoped user.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f1b8d40a37"
down_revision: Union[str, None] = "d5e9a3c07f26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("digests", sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_digests_site_id", "digests", "sites", ["site_id"], ["id"])
    op.create_index("ix_digests_site_id", "digests", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_digests_site_id", table_name="digests")
    op.drop_constraint("fk_digests_site_id", "digests", type_="foreignkey")
    op.drop_column("digests", "site_id")
