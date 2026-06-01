import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.models.organization import Organization
from app.models.site import Site
from app.models.camera import Camera
from app.models.event import Event
from app.services.digest.service import DigestService
from app.services.digest.gemini_client import GeminiResult


async def _seed_org_with_events(db_session, n_events: int):
    org = Organization(
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:6]}",
        whatsapp_number="919876543210",
    )
    db_session.add(org)
    await db_session.flush()
    site = Site(org_id=org.id, name="Home")
    db_session.add(site)
    await db_session.flush()
    cam = Camera(
        org_id=org.id,
        site_id=site.id,
        name="Front",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://x",
        status="online",
    )
    db_session.add(cam)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for i in range(n_events):
        db_session.add(Event(
            org_id=org.id,
            camera_id=cam.id,
            site_id=site.id,
            timestamp=now - timedelta(minutes=10 * i),
            event_type="motion",
            confidence=0.9,
            severity="medium",
            description=f"event {i}",
            snapshot_url="gs://x/snap.webp",
        ))
    await db_session.flush()
    return org, now


@pytest.mark.asyncio
async def test_generate_empty_window_creates_quiet_digest(db_session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    gemini = MagicMock()
    gemini.summarize = AsyncMock()  # should NOT be called
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session,
        gemini=gemini,
        spend_tracker=spend,
        notification=notif,
        dashboard_base_url="https://app",
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=8)

    digest = await svc.generate(
        org_id=org.id, kind="scheduled_morning", start=start, end=end
    )
    assert digest.event_count == 0
    assert digest.payload["headline"] == "All quiet"
    gemini.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_with_events_calls_gemini_and_persists(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=3)
    gemini = MagicMock()
    gemini.summarize = AsyncMock(return_value=GeminiResult(
        payload={
            "headline": "Three events", "period": "Last night",
            "total_events": 3, "by_severity": {"medium": 3},
            "narrative": "Activity was modest.", "highlights": [], "quiet_periods": []
        },
        cost_usd=0.03,
    ))
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="scheduled_evening",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )

    assert digest.event_count == 3
    assert digest.payload["headline"] == "Three events"
    notif.send_text_whatsapp.assert_awaited_once()
    assert "whatsapp" in digest.delivered_channels


@pytest.mark.asyncio
async def test_generate_falls_back_to_degraded_on_gemini_failure(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=2)
    gemini = MagicMock()
    gemini.summarize = AsyncMock(side_effect=RuntimeError("gemini down"))
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="on_demand",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )
    assert digest.payload["degraded"] is True
    assert digest.event_count == 2


@pytest.mark.asyncio
async def test_generate_skips_gemini_when_spend_cap_hit(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=2)
    gemini = MagicMock()
    gemini.summarize = AsyncMock()
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=False)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="on_demand",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )
    assert digest.payload["degraded"] is True
    gemini.summarize.assert_not_awaited()
