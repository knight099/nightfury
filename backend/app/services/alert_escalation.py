"""Escalation ladder: chase an alert nobody has acknowledged.

Today an alert rule fires once and stops. On a home box that is fine — the
owner either saw it or did not. A mall control room needs the opposite: an
event nobody picked up must climb — duty manager, then security head, then the
GM — until somebody acknowledges it.

This is **scheduling on top of the existing delivery path**, not a new channel.
Rungs reuse ``notification_service`` and write ``AlertHistory`` rows exactly as
a first-fire does, so escalated alerts appear in history like any other.

It depends on the incident workflow (``events.status``): "unacknowledged" has
to be a real, queryable state before anything can escalate on its absence.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_history import AlertHistory
from app.models.alert_rule import AlertRule
from app.models.event import Event
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)

# Statuses that stop the ladder. Anything else means the event is still
# waiting on a human.
ACKNOWLEDGED_STATUSES = ("acknowledged", "resolved", "dismissed")

# Only look back this far. An escalation that fires a day late is noise, not a
# safety net — and it bounds the sweep's query regardless of table size.
MAX_LOOKBACK = timedelta(hours=24)


def due_rungs(
    escalation: list[dict], event_age_seconds: float, already_fired: set[int]
) -> list[tuple[int, dict]]:
    """Which rungs should fire now, as ``(index, rung)`` pairs.

    Pure — no DB, no clock — so the ladder's timing logic can be reasoned
    about on its own.

    A rung fires when the event is older than its ``after_seconds`` and it has
    not fired before. Rungs are indexed by position, so reordering or editing a
    rule mid-incident cannot silently re-fire an earlier rung.
    """
    due = []
    for index, rung in enumerate(escalation):
        if index in already_fired:
            continue
        after = rung.get("after_seconds")
        if not isinstance(after, (int, float)):
            continue
        if event_age_seconds >= after:
            due.append((index, rung))
    return due


async def _fired_rungs(db: AsyncSession, event_id: uuid.UUID, rule_id: uuid.UUID) -> set[int]:
    """Rung indices already delivered for this event+rule.

    Derived from AlertHistory rather than tracked on the event, so the ladder
    has no state of its own to drift out of sync — history IS the record of
    what was sent.
    """
    rows = await db.execute(
        select(AlertHistory.escalation_rung).where(
            AlertHistory.event_id == event_id,
            AlertHistory.rule_id == rule_id,
            AlertHistory.escalation_rung.isnot(None),
        )
    )
    return {r for (r,) in rows.all() if r is not None}


async def sweep(db: AsyncSession, now: datetime | None = None) -> int:
    """Fire any due escalation rungs. Returns the number of notifications sent.

    Idempotent by construction: a rung already present in AlertHistory is
    never re-sent, so running the sweep twice in the same window is harmless.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - MAX_LOOKBACK

    # Candidate events: still unacknowledged, recent enough to be worth
    # chasing. The (org_id, status, timestamp) index covers this.
    events = (
        (
            await db.execute(
                select(Event).where(
                    Event.status.notin_(ACKNOWLEDGED_STATUSES),
                    Event.timestamp >= cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return 0

    org_ids = {e.org_id for e in events}
    rules = (
        (
            await db.execute(
                select(AlertRule).where(
                    AlertRule.org_id.in_(org_ids),
                    AlertRule.enabled.is_(True),
                    AlertRule.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    rules_with_ladder = [r for r in rules if r.escalation]
    if not rules_with_ladder:
        return 0

    from app.services.alert_service import alert_service  # avoid import cycle

    sent = 0
    for event in events:
        age = (now - _aware(event.timestamp)).total_seconds()
        for rule in rules_with_ladder:
            if rule.org_id != event.org_id:
                continue
            # Same matching rules as the first fire — an escalation must not
            # reach people the rule would never have notified in the first
            # place.
            if not alert_service._matches(rule, event):
                continue

            already = await _fired_rungs(db, event.id, rule.id)
            for index, rung in due_rungs(rule.escalation, age, already):
                for contact in rung.get("contacts", []):
                    success = await notification_service.send(
                        channel=contact["type"],
                        recipient=contact["value"],
                        event=event,
                        rule=rule,
                        webhook_url=rule.webhook_url,
                    )
                    db.add(
                        AlertHistory(
                            org_id=event.org_id,
                            rule_id=rule.id,
                            event_id=event.id,
                            channel=contact["type"],
                            recipient=contact["value"],
                            status="sent" if success else "failed",
                            escalation_rung=index,
                        )
                    )
                    sent += 1
                logger.info(
                    "escalated event %s rule %s to rung %d after %.0fs",
                    event.id,
                    rule.id,
                    index,
                    age,
                )

    await db.flush()
    return sent


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def run_escalation_sweep() -> None:
    """Scheduler entrypoint: owns its own session and never raises.

    A failure here must not kill the scheduler job — a dead sweep would
    silently stop every escalation ladder in the product, which is worse than
    one missed pass.
    """
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            sent = await sweep(db)
            if sent:
                await db.commit()
                logger.info("escalation sweep sent %d notification(s)", sent)
    except Exception:
        logger.exception("escalation sweep failed")
