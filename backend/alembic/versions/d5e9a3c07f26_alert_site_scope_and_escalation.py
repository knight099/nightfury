"""alert rule site scope + escalation ladder

Revision ID: d5e9a3c07f26
Revises: c3d7f2b9e814
Create Date: 2026-08-18

Two additive changes, both defaulting to today's behaviour:

* ``alert_rules.site_id`` — NULL means "all sites", so every existing rule
  keeps matching exactly what it matches now. Without it a multi-site operator
  manages one flat rule list with no way to scope a rule to one building.

* ``alert_rules.escalation`` — an empty ladder means "notify once, never
  chase", which is what every rule does today.

* ``alert_history.escalation_rung`` — records which rung produced a delivery
  (NULL = the initial fire). The escalation sweep derives "what have I already
  sent?" from this column rather than tracking state of its own, which is what
  makes it idempotent across restarts.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e9a3c07f26"
down_revision: Union[str, None] = "c3d7f2b9e814"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert_rules", sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key("fk_alert_rules_site_id", "alert_rules", "sites", ["site_id"], ["id"])

    op.add_column(
        "alert_rules",
        sa.Column(
            "escalation",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )

    op.add_column("alert_history", sa.Column("escalation_rung", sa.Integer(), nullable=True))
    op.create_index(
        "ix_alert_history_event_rule", "alert_history", ["event_id", "rule_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_alert_history_event_rule", table_name="alert_history")
    op.drop_column("alert_history", "escalation_rung")
    op.drop_column("alert_rules", "escalation")
    op.drop_constraint("fk_alert_rules_site_id", "alert_rules", type_="foreignkey")
    op.drop_column("alert_rules", "site_id")
