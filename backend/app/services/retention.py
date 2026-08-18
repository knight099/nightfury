"""Event retention: delete events and their media past an org's window.

Two reasons this exists, and both matter:

* **Compliance.** Under DPDP, "how long do you keep it and who decides" needs a
  product answer, not an operational promise. Snapshots and clips currently
  accumulate in object storage indefinitely.
* **Scale.** Retention is what bounds storage growth. At 300+ cameras producing
  snapshots and ~10s clips continuously, an unbounded event table and bucket is
  a cost curve with no ceiling.

Stored in ``organizations.settings['retention_days']`` rather than as a new
column: the JSONB field already exists for exactly this kind of per-org policy,
and this avoids a migration for one integer.

**Absent or zero means keep forever** — the current behaviour. Retention has to
be opt-in, because silently starting to delete a customer's evidence because a
default appeared in a deploy would be indefensible.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.services.gcs import delete_gcs_object

logger = logging.getLogger(__name__)

SETTINGS_KEY = "retention_days"

# Guard rails on the configured value. A window under a day risks deleting
# events an operator is still working; the upper bound stops a typo (3650)
# from silently meaning "forever" when the customer asked for a year.
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365 * 3

# Bound each pass so one org with a huge backlog cannot monopolise the job or
# hold a long transaction. The sweep runs daily and simply catches up.
BATCH_LIMIT = 5000


def retention_days_for(org: Organization) -> int | None:
    """Configured window, or None for "keep forever"."""
    raw = (org.settings or {}).get(SETTINGS_KEY)
    if raw is None:
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        logger.warning("org %s has non-numeric %s: %r", org.id, SETTINGS_KEY, raw)
        return None
    if days <= 0:
        return None
    return max(MIN_RETENTION_DAYS, min(days, MAX_RETENTION_DAYS))


async def purge_org(db: AsyncSession, org: Organization, now: datetime | None = None) -> int:
    """Delete expired events for one org. Returns how many rows went.

    Media is deleted before the row. If media deletion fails the row is kept,
    so the next pass retries it — the opposite order would orphan objects in
    the bucket with nothing left pointing at them.
    """
    days = retention_days_for(org)
    if days is None:
        return 0

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    expired = (
        (
            await db.execute(
                select(Event)
                .where(Event.org_id == org.id, Event.timestamp < cutoff)
                .order_by(Event.timestamp)
                .limit(BATCH_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if not expired:
        return 0

    deletable_ids = []
    for event in expired:
        ok = True
        for uri in (event.snapshot_url, event.clip_url):
            if uri and not delete_gcs_object(uri):
                ok = False
        if ok:
            deletable_ids.append(event.id)
        else:
            logger.warning(
                "retention: keeping event %s — media delete failed, will retry", event.id
            )

    if not deletable_ids:
        return 0

    await db.execute(delete(Event).where(Event.id.in_(deletable_ids)))
    await db.flush()
    logger.info(
        "retention: purged %d event(s) for org %s older than %d days",
        len(deletable_ids),
        org.id,
        days,
    )
    return len(deletable_ids)


async def purge_all(db: AsyncSession, now: datetime | None = None) -> int:
    """Run retention for every org that has configured a window."""
    orgs = (
        (await db.execute(select(Organization).where(Organization.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    total = 0
    for org in orgs:
        try:
            total += await purge_org(db, org, now)
        except Exception:
            # One org's failure must not stop the rest — a stuck bucket or a
            # bad settings value should not halt retention estate-wide.
            logger.exception("retention failed for org %s", org.id)
    return total


async def run_retention_sweep() -> None:
    """Scheduler entrypoint: owns its session, never raises."""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            purged = await purge_all(db)
            if purged:
                await db.commit()
                logger.info("retention sweep purged %d event(s)", purged)
    except Exception:
        logger.exception("retention sweep failed")
