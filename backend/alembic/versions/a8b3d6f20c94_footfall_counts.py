"""footfall_counts + cameras.counting_lines

Revision ID: a8b3d6f20c94
Revises: f7a2c9e15b48
Create Date: 2026-08-18

Raw per-heartbeat buckets rather than a running total: a total cannot be
corrected or re-aggregated later, and one duplicated heartbeat would corrupt
it permanently. Buckets can simply be summed at read time.

These are estimates from tracking without re-identification — see
agent/pipeline/footfall.py for the specific error modes. Readers must present
them as relative trend, not absolute visitor counts.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8b3d6f20c94"
down_revision: Union[str, None] = "f7a2c9e15b48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("counting_lines", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="[]"),
    )
    op.create_table(
        "footfall_counts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("line_name", sa.String(100), nullable=False),
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("count_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_footfall_org_bucket", "footfall_counts", ["org_id", "bucket_at"])
    op.create_index("ix_footfall_camera_bucket", "footfall_counts", ["camera_id", "bucket_at"])


def downgrade() -> None:
    op.drop_table("footfall_counts")
    op.drop_column("cameras", "counting_lines")
