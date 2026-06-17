"""Tests for /api/events — list, detail, feedback, stats."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.camera import Camera
from app.models.event import Event
from app.models.site import Site


def _make_site(org_id):
    return Site(org_id=org_id, name="HQ", timezone="Asia/Kolkata")


def _make_camera(org_id, site_id):
    return Camera(
        org_id=org_id,
        site_id=site_id,
        name="Front Door",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://10.0.0.1/stream",
    )


def _make_event(org_id, camera_id, site_id, **kwargs):
    defaults = dict(
        org_id=org_id,
        camera_id=camera_id,
        site_id=site_id,
        timestamp=datetime.now(timezone.utc),
        event_type="person",
        confidence=0.92,
        severity="high",
        description="Person detected near entrance",
        snapshot_url="gs://bucket/snap.webp",
    )
    defaults.update(kwargs)
    return Event(**defaults)


@pytest.mark.asyncio
async def test_list_events_empty(auth_client):
    resp = await auth_client.get("/api/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_events_returns_org_scoped_events(auth_client, db_session, test_org, test_user):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other Org", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_site = _make_site(other_org.id)
    db_session.add(other_site)
    await db_session.flush()

    other_cam = _make_camera(other_org.id, other_site.id)
    db_session.add(other_cam)
    await db_session.flush()

    my_event = _make_event(test_org.id, cam.id, site.id)
    other_event = _make_event(other_org.id, other_cam.id, other_site.id)
    db_session.add_all([my_event, other_event])
    await db_session.flush()

    resp = await auth_client.get("/api/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == str(my_event.id)


@pytest.mark.asyncio
async def test_list_events_filter_by_severity(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    high = _make_event(test_org.id, cam.id, site.id, severity="high")
    low = _make_event(test_org.id, cam.id, site.id, severity="low")
    db_session.add_all([high, low])
    await db_session.flush()

    resp = await auth_client.get("/api/events?severity=high")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["severity"] == "high"


@pytest.mark.asyncio
async def test_list_events_filter_by_camera(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam1 = _make_camera(test_org.id, site.id)
    cam2 = _make_camera(test_org.id, site.id)
    db_session.add_all([cam1, cam2])
    await db_session.flush()

    ev1 = _make_event(test_org.id, cam1.id, site.id)
    ev2 = _make_event(test_org.id, cam2.id, site.id)
    db_session.add_all([ev1, ev2])
    await db_session.flush()

    resp = await auth_client.get(f"/api/events?camera_id={cam1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["camera_id"] == str(cam1.id)


@pytest.mark.asyncio
async def test_list_events_pagination(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    events = [_make_event(test_org.id, cam.id, site.id) for _ in range(5)]
    db_session.add_all(events)
    await db_session.flush()

    resp = await auth_client.get("/api/events?page=1&per_page=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["events"]) == 2
    assert body["pages"] == 3


@pytest.mark.asyncio
async def test_get_event_detail(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    ev = _make_event(test_org.id, cam.id, site.id, description="Suspicious activity")
    db_session.add(ev)
    await db_session.flush()

    resp = await auth_client.get(f"/api/events/{ev.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(ev.id)
    assert body["description"] == "Suspicious activity"


@pytest.mark.asyncio
async def test_get_event_not_found(auth_client):
    resp = await auth_client.get(f"/api/events/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_event_other_org_returns_404(auth_client, db_session, test_org):
    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_site = _make_site(other_org.id)
    db_session.add(other_site)
    await db_session.flush()

    other_cam = _make_camera(other_org.id, other_site.id)
    db_session.add(other_cam)
    await db_session.flush()

    other_event = _make_event(other_org.id, other_cam.id, other_site.id)
    db_session.add(other_event)
    await db_session.flush()

    resp = await auth_client.get(f"/api/events/{other_event.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_approve(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    ev = _make_event(test_org.id, cam.id, site.id)
    db_session.add(ev)
    await db_session.flush()

    resp = await auth_client.post(
        f"/api/events/{ev.id}/feedback",
        json={"feedback": "approved"},
    )
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "approved"

    await db_session.refresh(ev)
    assert ev.feedback == "approved"


@pytest.mark.asyncio
async def test_submit_feedback_reclassify(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    ev = _make_event(test_org.id, cam.id, site.id)
    db_session.add(ev)
    await db_session.flush()

    resp = await auth_client.post(
        f"/api/events/{ev.id}/feedback",
        json={"feedback": "reclassified", "label": "false_positive"},
    )
    assert resp.status_code == 200
    await db_session.refresh(ev)
    assert ev.feedback == "reclassified"
    assert ev.feedback_label == "false_positive"


@pytest.mark.asyncio
async def test_event_stats_returns_counts(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = _make_camera(test_org.id, site.id)
    db_session.add(cam)
    await db_session.flush()

    ev1 = _make_event(test_org.id, cam.id, site.id, event_type="person", severity="high")
    ev2 = _make_event(test_org.id, cam.id, site.id, event_type="vehicle", severity="low")
    db_session.add_all([ev1, ev2])
    await db_session.flush()

    resp = await auth_client.get("/api/events/stats?period=24h")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 2
    assert body["by_type"]["person"] == 1
    assert body["by_type"]["vehicle"] == 1


@pytest.mark.asyncio
async def test_events_unauthenticated(client):
    # Required Authorization header missing → 422 Unprocessable Entity
    resp = await client.get("/api/events")
    assert resp.status_code == 422
