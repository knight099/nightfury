"""camera_connections — manually-drawn adjacency for journeys

Revision ID: f7a2c9e15b48
Revises: e6f1b8d40a37
Create Date: 2026-08-18

An operator-drawn graph of which cameras are physically adjacent ("joined by
a hallway"). Journeys correlate events across these edges by timing.

Explicitly NOT person re-identification: no embeddings, no biometrics, no
visual matching. The unique index enforces the unordered pair, with the
application storing (min, max) so (A,B) and (B,A) cannot both exist.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a2c9e15b48"
down_revision: Union[str, None] = "e6f1b8d40a37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "camera_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("camera_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("camera_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_camera_connections_site", "camera_connections", ["site_id"])
    op.create_index("ix_camera_connections_a", "camera_connections", ["camera_a_id"])
    op.create_index("ix_camera_connections_b", "camera_connections", ["camera_b_id"])
    # Normalised (min, max) storage makes this enough to dedupe the unordered
    # pair — no application-level "does the reverse already exist?" check.
    op.create_unique_constraint(
        "uq_camera_connection_pair", "camera_connections", ["camera_a_id", "camera_b_id"]
    )
    # A camera cannot be adjacent to itself.
    op.create_check_constraint(
        "ck_camera_connection_distinct", "camera_connections", "camera_a_id <> camera_b_id"
    )


def downgrade() -> None:
    op.drop_table("camera_connections")
