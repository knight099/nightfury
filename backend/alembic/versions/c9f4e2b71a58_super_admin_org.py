"""give super_admin its own organisation

Revision ID: c9f4e2b71a58
Revises: b4c8e1a90d37

super_admin used to have org_id = NULL. That made every "my org" surface —
settings, sites, team, digests — return 400 for them, so a super admin could
not create a site or add a camera to test with, and the settings page rendered
four blank tabs.

Cross-org visibility never depended on the null: all 26 org-filter bypasses
key off `role == "super_admin"`, not off org_id. So attaching super admins to
a real organisation restores the "my org" surfaces and changes nothing about
what they can see.

This backfills existing deployments. `seed_super_admin` also repairs on boot,
but a deployment that does not restart before someone logs in would otherwise
stay broken.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9f4e2b71a58"
down_revision: Union[str, None] = "b4c8e1a90d37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the super org only if it is absent, so this is safe to re-run and
    # agrees with what seed_super_admin creates (same slug).
    op.execute(
        """
        INSERT INTO organizations (id, name, slug, plan, timezone, settings, created_at, updated_at)
        SELECT gen_random_uuid(), 'Nightwatch HQ', 'nightwatch-hq', 'internal',
               'Asia/Kolkata', '{}'::jsonb, now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'nightwatch-hq')
        """
    )
    op.execute(
        """
        UPDATE users
        SET org_id = (SELECT id FROM organizations WHERE slug = 'nightwatch-hq')
        WHERE role = 'super_admin' AND org_id IS NULL
        """
    )


def downgrade() -> None:
    # Detach super admins; leave the org itself in place because sites,
    # cameras and events may now belong to it, and dropping it would cascade
    # into deleting a customer's test setup.
    op.execute(
        """
        UPDATE users SET org_id = NULL
        WHERE role = 'super_admin'
          AND org_id = (SELECT id FROM organizations WHERE slug = 'nightwatch-hq')
        """
    )
