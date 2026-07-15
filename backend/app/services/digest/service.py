import logging
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.digest import Digest
from app.models.event import Event
from app.models.organization import Organization
from app.services.digest.compactor import compact_events
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.renderer import (
    build_degraded_payload,
    build_quiet_payload,
    render_whatsapp_message,
)
from app.services.digest.sampler import sample_evenly
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import NotificationService
from app.ws.events import broadcast_to_org

logger = logging.getLogger(__name__)


DigestKind = Literal["scheduled_morning", "scheduled_evening", "on_demand"]


class DigestService:
    def __init__(
        self,
        db: AsyncSession,
        gemini: GeminiDigestClient,
        spend_tracker: SpendTracker,
        notification: NotificationService,
        dashboard_base_url: str,
    ):
        self.db = db
        self.gemini = gemini
        self.spend = spend_tracker
        self.notification = notification
        self.dashboard_base_url = dashboard_base_url.rstrip("/")

    async def generate(
        self,
        *,
        org_id: uuid.UUID,
        kind: DigestKind,
        start: datetime,
        end: datetime,
        camera_ids: list[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> Digest:
        org = (
            await self.db.execute(
                select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
            )
        ).scalar_one()

        events_rows = await self._load_events(org_id, start, end, camera_ids, site_id)
        period_label = self._period_label(kind, start, end)

        # Empty window
        if not events_rows:
            payload = build_quiet_payload(period_label)
            return await self._persist_and_deliver(
                org=org, kind=kind, start=start, end=end, payload=payload,
                event_count=0, requested_by=requested_by,
            )

        # Sample down if needed
        sampled = sample_evenly(events_rows, cap=settings.digest_max_events_per_window)
        compact = compact_events([self._event_to_dict(e) for e in sampled])

        # Spend cap
        cost_estimate = 0.03  # matches APPROX_COST_PER_CALL_USD
        allowed = await self.spend.try_charge(org_id, cost_estimate)
        if not allowed:
            logger.warning("Spend cap reached for org %s — emitting degraded digest", org_id)
            payload = build_degraded_payload(
                [self._event_to_dict(e) for e in sampled], period_label
            )
            return await self._persist_and_deliver(
                org=org, kind=kind, start=start, end=end, payload=payload,
                event_count=len(events_rows), requested_by=requested_by,
            )

        # Gemini call (with degraded fallback on failure)
        try:
            result = await self.gemini.summarize(compact, period_label)
            payload = result.payload
            payload.setdefault("degraded", False)
        except Exception as e:
            logger.error("Gemini summarize failed for org %s: %s", org_id, e)
            payload = build_degraded_payload(
                [self._event_to_dict(ev) for ev in sampled], period_label
            )

        return await self._persist_and_deliver(
            org=org, kind=kind, start=start, end=end, payload=payload,
            event_count=len(events_rows), requested_by=requested_by,
        )

    async def _load_events(self, org_id, start, end, camera_ids, site_id):
        stmt = (
            select(Event)
            .options(selectinload(Event.camera))
            .where(Event.org_id == org_id)
            .where(Event.timestamp >= start)
            .where(Event.timestamp < end)
            .order_by(Event.timestamp.asc())
        )
        if camera_ids:
            stmt = stmt.where(Event.camera_id.in_(camera_ids))
        if site_id:
            stmt = stmt.where(Event.site_id == site_id)
        return list((await self.db.execute(stmt)).scalars().all())

    def _event_to_dict(self, e: Event) -> dict:
        return {
            "id": e.id,
            "timestamp": e.timestamp,
            "camera_name": getattr(e.camera, "name", None) if hasattr(e, "camera") and e.camera else None,
            "event_type": e.event_type,
            "severity": e.severity,
            "description": e.description,
            "confidence": e.confidence,
        }

    def _period_label(self, kind, start, end) -> str:
        if kind == "scheduled_morning":
            return "Last night"
        if kind == "scheduled_evening":
            return "Today"
        return f"{start.strftime('%Y-%m-%d %H:%M')} – {end.strftime('%Y-%m-%d %H:%M')}"

    async def _persist_and_deliver(
        self, *, org: Organization, kind, start, end, payload, event_count, requested_by
    ) -> Digest:
        digest = Digest(
            org_id=org.id,
            kind=kind,
            range_start=start,
            range_end=end,
            event_count=event_count,
            payload=payload,
            delivered_channels=["dashboard"],
            requested_by=requested_by,
        )
        self.db.add(digest)
        # NOTE: use flush (not commit) so the caller controls the transaction
        # boundary. Tests rely on rollback-after-test isolation.
        await self.db.flush()
        await self.db.refresh(digest)

        # WhatsApp delivery (if configured)
        if org.whatsapp_number:
            url = f"{self.dashboard_base_url}/digests/{digest.id}"
            text = render_whatsapp_message(payload, dashboard_url=url)
            ok = await self.notification.send_text_whatsapp(org.whatsapp_number, text)
            if ok:
                digest.delivered_channels = list(digest.delivered_channels) + ["whatsapp"]
                await self.db.flush()

        # Broadcast WS event
        try:
            await broadcast_to_org(str(org.id), {
                "type": "digest.ready",
                "digest_id": str(digest.id),
                "kind": kind,
                "headline": payload.get("headline"),
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
            })
        except Exception:
            logger.exception("Failed to broadcast digest.ready for digest %s", digest.id)

        return digest
