from datetime import datetime, time, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.alert_history import AlertHistory
from app.models.alert_rule import AlertRule
from app.models.event import Event
from app.services.notification_service import notification_service


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class AlertService:
    async def evaluate_event(self, event: Event, db: AsyncSession) -> int:
        result = await db.execute(
            select(AlertRule).where(
                AlertRule.org_id == event.org_id,
                AlertRule.enabled == True,
                AlertRule.deleted_at.is_(None),
            )
        )
        rules = result.scalars().all()
        triggered_count = 0

        redis_client = await get_redis()

        for rule in rules:
            if not self._matches(rule, event):
                continue

            if await self._is_in_cooldown(redis_client, rule, event):
                continue

            for contact in rule.notify_contacts:
                success = await notification_service.send(
                    channel=contact["type"],
                    recipient=contact["value"],
                    event=event,
                    rule=rule,
                    webhook_url=rule.webhook_url,
                )

                history = AlertHistory(
                    org_id=event.org_id,
                    rule_id=rule.id,
                    event_id=event.id,
                    channel=contact["type"],
                    recipient=contact["value"],
                    status="sent" if success else "failed",
                )
                db.add(history)
                triggered_count += 1

            await self._set_cooldown(redis_client, rule, event)

        await db.flush()
        return triggered_count

    def _matches(self, rule: AlertRule, event: Event) -> bool:
        if rule.event_types and event.event_type not in rule.event_types:
            return False

        if SEVERITY_ORDER.get(event.severity, 0) < SEVERITY_ORDER.get(rule.min_severity, 0):
            return False

        if rule.cameras and event.camera_id not in rule.cameras:
            return False

        if rule.time_window:
            if not self._in_time_window(event.timestamp, rule.time_window):
                return False

        if rule.zones:
            event_zone = event.metadata_extra.get("zone") if event.metadata_extra else None
            if event_zone and event_zone not in rule.zones:
                return False

        return True

    def _in_time_window(self, event_time: datetime, window: dict) -> bool:
        start_str = window.get("start", "00:00")
        end_str = window.get("end", "23:59")
        days = window.get("days", [])

        day_name = event_time.strftime("%a").lower()
        if days and day_name not in days:
            return False

        start = time(*map(int, start_str.split(":")))
        end = time(*map(int, end_str.split(":")))
        event_t = event_time.time()

        if start <= end:
            return start <= event_t <= end
        else:  # overnight window (e.g., 22:00 - 06:00)
            return event_t >= start or event_t <= end

    async def _is_in_cooldown(self, redis_client: aioredis.Redis, rule: AlertRule, event: Event) -> bool:
        key = f"cooldown:{rule.id}:{event.camera_id}:{event.event_type}"
        return await redis_client.exists(key)

    async def _set_cooldown(self, redis_client: aioredis.Redis, rule: AlertRule, event: Event):
        key = f"cooldown:{rule.id}:{event.camera_id}:{event.event_type}"
        await redis_client.setex(key, rule.cooldown_seconds, "1")


alert_service = AlertService()
