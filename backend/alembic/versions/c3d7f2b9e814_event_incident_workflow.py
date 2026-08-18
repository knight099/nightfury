"""event incident workflow (status / acknowledge / resolve)

Revision ID: c3d7f2b9e814
Revises: b1c4e7a2d9f3
Create Date: 2026-08-18

Adds operational state to `events`, kept strictly separate from the existing
`feedback` columns.

`feedback` answers "was the detection correct?" — it trains and audits the AI.
`status` answers "did somebody deal with it?" — it runs the control room.
These are independent: a true detection can sit unresolved, and a false one
can be dismissed. Collapsing them into one column would make a shift handover
unable to distinguish "reviewed the AI's guess" from "sent someone to look".

Existing rows get status='new'. That is honest rather than convenient — those
events genuinely were never acknowledged, because until now there was no way
to acknowledge one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d7f2b9e814"
down_revision: Union[str, None] = "b1c4e7a2d9f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
    )
    op.add_column(
        "events", sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "events", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "events", sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("resolution_note", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_events_acknowledged_by", "events", "users", ["acknowledged_by"], ["id"]
    )
    op.create_foreign_key("fk_events_resolved_by", "events", "users", ["resolved_by"], ["id"])

    # "What is still open at this site" is the query a control room runs
    # constantly, and it filters status before ordering by time.
    op.create_index(
        "ix_events_org_status_timestamp",
        "events",
        ["org_id", "status", sa.text("timestamp DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_events_org_status_timestamp", table_name="events")
    op.drop_constraint("fk_events_resolved_by", "events", type_="foreignkey")
    op.drop_constraint("fk_events_acknowledged_by", "events", type_="foreignkey")
    op.drop_column("events", "resolution_note")
    op.drop_column("events", "resolved_at")
    op.drop_column("events", "resolved_by")
    op.drop_column("events", "acknowledged_at")
    op.drop_column("events", "acknowledged_by")
    op.drop_column("events", "status")
