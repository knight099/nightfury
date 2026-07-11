import logging
from datetime import datetime, time, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.models.digest_preferences import DigestPreferences
from app.models.organization import Organization
from app.services.digest.deps import _gemini_client
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.service import DigestService
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import notification_service

try:  # APScheduler is optional in dev/CI
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
    from apscheduler.triggers.cron import CronTrigger  # type: ignore
    APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover
    AsyncIOScheduler = None  # type: ignore
    CronTrigger = None  # type: ignore
    APSCHEDULER_AVAILABLE = False

logger = logging.getLogger(__name__)


def compute_morning_window(
    now_local: datetime, morning_local_time: time
) -> Tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes covering 22:00 prior day → morning_local_time today."""
    end_local = now_local.replace(
        hour=morning_local_time.hour,
        minute=morning_local_time.minute,
        second=0,
        microsecond=0,
    )
    # Step back to 22:00 of the previous day (relative to end_local)
    start_local = (end_local - timedelta(hours=9)).replace(
        hour=22, minute=0, second=0, microsecond=0
    )
    return (
        start_local.astimezone(ZoneInfo("UTC")),
        end_local.astimezone(ZoneInfo("UTC")),
    )


def compute_evening_window(
    now_local: datetime, evening_local_time: time
) -> Tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes covering 07:00 today → evening_local_time today."""
    end_local = now_local.replace(
        hour=evening_local_time.hour,
        minute=evening_local_time.minute,
        second=0,
        microsecond=0,
    )
    start_local = end_local.replace(hour=7, minute=0, second=0, microsecond=0)
    return (
        start_local.astimezone(ZoneInfo("UTC")),
        end_local.astimezone(ZoneInfo("UTC")),
    )


async def _run_for_org(org_id, kind: str):
    async with async_session_factory() as db:
        org = (
            await db.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one()
        prefs = (
            await db.execute(
                select(DigestPreferences).where(DigestPreferences.org_id == org_id)
            )
        ).scalar_one_or_none()
        if prefs is None:
            return
        tz = ZoneInfo(org.timezone or "Asia/Kolkata")
        now_local = datetime.now(tz)
        if kind == "scheduled_morning":
            if not prefs.morning_enabled:
                return
            start, end = compute_morning_window(now_local, prefs.morning_local_time)
        else:
            if not prefs.evening_enabled:
                return
            start, end = compute_evening_window(now_local, prefs.evening_local_time)

        redis = await get_redis()
        gemini = GeminiDigestClient(genai_client=_gemini_client())
        spend = SpendTracker(
            redis_client=redis, daily_cap_usd=settings.digest_daily_spend_cap_usd
        )
        service = DigestService(
            db=db,
            gemini=gemini,
            spend_tracker=spend,
            notification=notification_service,
            dashboard_base_url=settings.dashboard_base_url,
        )
        try:
            await service.generate(org_id=org.id, kind=kind, start=start, end=end)
            await db.commit()
        except Exception:
            logger.exception(
                "Scheduled digest failed for org %s kind %s", org.id, kind
            )
            await db.rollback()


async def schedule_all(scheduler) -> None:
    """Iterate orgs and add cron jobs in each org's local timezone."""
    if not APSCHEDULER_AVAILABLE:
        logger.warning("apscheduler unavailable; skipping schedule_all")
        return
    async with async_session_factory() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()
        for org in orgs:
            tz = org.timezone or "Asia/Kolkata"
            prefs = (
                await db.execute(
                    select(DigestPreferences).where(DigestPreferences.org_id == org.id)
                )
            ).scalar_one_or_none()
            morning = prefs.morning_local_time if prefs else time(7, 0)
            evening = prefs.evening_local_time if prefs else time(19, 0)

            scheduler.add_job(
                _run_for_org,
                args=[org.id, "scheduled_morning"],
                trigger=CronTrigger(
                    hour=morning.hour, minute=morning.minute, timezone=tz
                ),
                id=f"morning:{org.id}",
                replace_existing=True,
            )
            scheduler.add_job(
                _run_for_org,
                args=[org.id, "scheduled_evening"],
                trigger=CronTrigger(
                    hour=evening.hour, minute=evening.minute, timezone=tz
                ),
                id=f"evening:{org.id}",
                replace_existing=True,
            )


def start_scheduler():
    """Start the APScheduler instance. Returns None if apscheduler is unavailable."""
    if not APSCHEDULER_AVAILABLE:
        logger.warning("apscheduler not installed; scheduled digests disabled")
        return None
    sched = AsyncIOScheduler()
    sched.start()
    return sched
