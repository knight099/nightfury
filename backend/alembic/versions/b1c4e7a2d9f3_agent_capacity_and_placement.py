"""agent capacity + camera placement backfill

Revision ID: b1c4e7a2d9f3
Revises: a3f6d1c9e8b4
Create Date: 2026-08-18

Adds the capacity/placement columns to ``agents`` and — critically — backfills
``cameras.agent_id``.

WHY THE BACKFILL IS NOT OPTIONAL
--------------------------------
Before this change ``GET /internal/assignments`` ignored the caller entirely
and returned every camera row in the database; each agent then locally took
the first ``max_cameras`` of them. After this change the endpoint returns only
cameras whose ``agent_id`` matches the calling agent.

That means any camera left with ``agent_id IS NULL`` stops being analysed by
anybody the moment the new code ships. Existing deployments have never
populated the column for cameras created through ``POST /api/cameras`` (only
the agent-registration path in ``api/agents.py`` sets it), so without this
backfill the migration would silently stop detection for live customers.

Single-agent orgs — the overwhelming majority, and the shape the product was
designed around — are backfilled here to exactly preserve today's behaviour.
Multi-agent orgs are deliberately left NULL: today those agents all duplicate
the same first-12 cameras, so there is no existing assignment worth
preserving. The placement reconciler distributes them on its first run
(triggered by any agent heartbeat), which is a better answer than guessing in
SQL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c4e7a2d9f3"
down_revision: Union[str, None] = "a3f6d1c9e8b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_agents_site_id", "agents", "sites", ["site_id"], ["id"])
    op.create_index("ix_agents_site_id", "agents", ["site_id"])

    op.add_column("agents", sa.Column("capacity_cameras", sa.Integer(), nullable=True))
    op.add_column(
        "agents",
        sa.Column("capacity_source", sa.String(16), nullable=False, server_default="declared"),
    )
    op.add_column(
        "agents", sa.Column("assigned_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "agents", sa.Column("assignment_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "agents", sa.Column("load_state", sa.String(16), nullable=False, server_default="ok")
    )
    op.add_column("agents", sa.Column("load_reason", sa.String(255), nullable=True))

    op.add_column(
        "cameras",
        sa.Column("pinned_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_cameras_pinned_agent_id", "cameras", "agents", ["pinned_agent_id"], ["id"]
    )

    # ── Backfill 1: cameras.agent_id for orgs that have exactly one agent ──
    # Preserves current behaviour exactly: that agent was already the only
    # thing analysing those cameras.
    op.execute(
        """
        UPDATE cameras c
        SET agent_id = sole.agent_id
        FROM (
            -- (array_agg(id))[1] rather than MIN(id): Postgres has no
            -- MIN() for uuid. HAVING COUNT(*) = 1 guarantees exactly one
            -- row per group, so taking the first element is the whole set.
            SELECT org_id, (array_agg(id))[1] AS agent_id
            FROM agents
            GROUP BY org_id
            HAVING COUNT(*) = 1
        ) AS sole
        WHERE c.org_id = sole.org_id
          AND c.agent_id IS NULL
          AND c.deleted_at IS NULL
        """
    )

    # ── Backfill 2: agents.site_id from the cameras already placed on them ──
    # An agent serves one LAN. Where its cameras all sit at one site, that is
    # its site. Where they straddle sites (shouldn't happen, but the data
    # allows it), pick the site holding the most of its cameras.
    op.execute(
        """
        UPDATE agents a
        SET site_id = best.site_id
        FROM (
            SELECT DISTINCT ON (agent_id) agent_id, site_id
            FROM cameras
            WHERE agent_id IS NOT NULL AND deleted_at IS NULL
            GROUP BY agent_id, site_id
            ORDER BY agent_id, COUNT(*) DESC, site_id
        ) AS best
        WHERE a.id = best.agent_id
          AND a.site_id IS NULL
        """
    )

    # ── Backfill 3: agents with no cameras, in an org that has one site ──
    op.execute(
        """
        UPDATE agents a
        SET site_id = only_site.site_id
        FROM (
            -- Same reason as above: no MIN() for uuid, and COUNT(*) = 1
            -- means the group holds exactly one site.
            SELECT org_id, (array_agg(id))[1] AS site_id
            FROM sites
            WHERE deleted_at IS NULL
            GROUP BY org_id
            HAVING COUNT(*) = 1
        ) AS only_site
        WHERE a.org_id = only_site.org_id
          AND a.site_id IS NULL
        """
    )

    # ── Backfill 4: assigned_count to match reality ──
    op.execute(
        """
        UPDATE agents a
        SET assigned_count = COALESCE(cnt.n, 0)
        FROM (
            SELECT agent_id, COUNT(*) AS n
            FROM cameras
            WHERE agent_id IS NOT NULL AND deleted_at IS NULL
            GROUP BY agent_id
        ) AS cnt
        WHERE a.id = cnt.agent_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_cameras_pinned_agent_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "pinned_agent_id")
    op.drop_column("agents", "load_reason")
    op.drop_column("agents", "load_state")
    op.drop_column("agents", "assignment_version")
    op.drop_column("agents", "assigned_count")
    op.drop_column("agents", "capacity_source")
    op.drop_column("agents", "capacity_cameras")
    op.drop_index("ix_agents_site_id", table_name="agents")
    op.drop_constraint("fk_agents_site_id", "agents", type_="foreignkey")
    op.drop_column("agents", "site_id")
