"""Appliance failover: notice a dead box and stop pretending its cameras are covered.

One agent going down takes its cameras with it. On a home box that is the
owner's problem; on a mall floor it is a coverage hole nobody is told about.

The mechanism reuses the placement reconciler rather than adding a parallel
path: marking a stale agent ``offline`` makes it fail ``plan_placement``'s
health check, so the very next reconcile moves its cameras to siblings with
spare capacity — or leaves them ``unassigned`` and visible if there is none.
There is no separate "failover algorithm" to keep in sync with placement.

**Two different thresholds, deliberately.** The fleet view calls a box stale
after ~100s so an operator sees a problem quickly. Failover waits much longer,
because moving cameras restarts streams: a box rebooting or briefly losing its
uplink should show as stale immediately but must not trigger a stampede of
reassignments that then have to be undone.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.camera import Camera
from app.models.organization import Organization
from app.services.camera_placement import reconcile_site
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)

# Long enough to ride out a reboot, a pipeline restart, or a brief uplink drop.
# Shorter than this and a routine restart costs every camera on the box a
# stream restart, twice (away and back).
FAILOVER_AFTER = timedelta(minutes=5)


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """Fail over agents that have stopped reporting. Returns how many.

    Idempotent: an agent already marked offline is skipped, so the sweep only
    acts on the online→offline transition and never re-notifies.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - FAILOVER_AFTER

    stale = (
        (
            await db.execute(
                select(Agent).where(
                    Agent.status == "online",
                    Agent.last_seen_at.isnot(None),
                    Agent.last_seen_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not stale:
        return 0

    for agent in stale:
        camera_count = (
            len(
                (
                    await db.execute(
                        select(Camera).where(
                            Camera.agent_id == agent.id, Camera.deleted_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
        )

        agent.status = "offline"
        agent.load_state = "ok"
        agent.load_reason = None
        await db.flush()

        # Reconcile AFTER the status flip: plan_placement only treats
        # status == "online" as healthy, so this is what actually relocates
        # the cameras (or exposes them as unassigned).
        plan = await reconcile_site(db, agent.org_id, agent.site_id)

        logger.warning(
            "agent %s (%s) stopped reporting; %d camera(s) affected, "
            "%d relocated, %d now unassigned",
            agent.id,
            agent.machine_id,
            camera_count,
            len(plan.moved),
            len(plan.unassigned),
        )
        await _notify_coverage_gap(db, agent, camera_count, len(plan.unassigned))

    return len(stale)


async def _notify_coverage_gap(
    db: AsyncSession, agent: Agent, camera_count: int, unassigned: int
) -> None:
    """Tell the customer a box went dark.

    A coverage gap is itself worth an alert: the whole promise is that
    something is watching, so silence when it stops is the one failure mode
    the product must never have. Sent as free-form text (the same path digests
    use) rather than through the alert-rule engine, which is shaped around
    Events and would need a fake one.
    """
    org = (
        await db.execute(select(Organization).where(Organization.id == agent.org_id))
    ).scalar_one_or_none()
    if org is None:
        return

    # Respect the per-contact `enabled` flag — a number the customer switched
    # off must not start receiving messages because a new alert type appeared.
    contacts = [
        c.get("number")
        for c in (org.whatsapp_alert_contacts or [])
        if c.get("number") and c.get("enabled")
    ]
    if not contacts:
        return

    if unassigned:
        detail = (
            f"{unassigned} of them are not being analysed — no spare capacity "
            f"at this site."
        )
    else:
        detail = "Their cameras have been moved to another appliance and are still covered."

    message = (
        f"Nightwatch: appliance '{agent.machine_id}' has stopped reporting. "
        f"{camera_count} camera(s) were assigned to it. {detail}"
    )

    for number in contacts:
        try:
            await notification_service.send_text_whatsapp(number, message)
        except Exception:
            logger.exception("coverage-gap notification failed for %s", number)


async def run_fleet_health_sweep() -> None:
    """Scheduler entrypoint: owns its session, never raises."""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            failed_over = await sweep(db)
            if failed_over:
                await db.commit()
                logger.info("fleet health sweep failed over %d agent(s)", failed_over)
    except Exception:
        logger.exception("fleet health sweep failed")
