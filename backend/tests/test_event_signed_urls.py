"""Tests for GCS signed URL generation on the events API."""

from datetime import datetime, timezone

import pytest

from app.models.camera import Camera
from app.models.event import Event
from app.models.site import Site
from app.services import gcs as gcs_service


def _fake_signer(uri, *args, **kwargs):
    if uri and isinstance(uri, str) and uri.startswith("gs://"):
        return f"https://signed.example/{uri}"
    return uri


async def _seed_event(db_session, test_org):
    site = Site(org_id=test_org.id, name="Site 1")
    db_session.add(site)
    await db_session.flush()

    camera = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Cam 1",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example.local/stream",
    )
    db_session.add(camera)
    await db_session.flush()

    event = Event(
        org_id=test_org.id,
        camera_id=camera.id,
        site_id=site.id,
        timestamp=datetime.now(timezone.utc),
        event_type="motion",
        confidence=0.95,
        severity="medium",
        description="Test event",
        bounding_boxes=[],
        snapshot_url="gs://bucket/snap.jpg",
        clip_url="gs://bucket/clip.mp4",
    )
    db_session.add(event)
    await db_session.flush()
    return event


@pytest.mark.asyncio
async def test_list_events_returns_signed_urls(
    auth_client, db_session, test_org, monkeypatch
):
    monkeypatch.setattr("app.api.events.sign_gcs_url", _fake_signer)
    event = await _seed_event(db_session, test_org)

    resp = await auth_client.get("/api/events")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1

    found = next((e for e in body["events"] if e["id"] == str(event.id)), None)
    assert found is not None
    assert found["snapshot_url"] == "https://signed.example/gs://bucket/snap.jpg"
    assert found["clip_url"] == "https://signed.example/gs://bucket/clip.mp4"


@pytest.mark.asyncio
async def test_get_event_returns_signed_urls(
    auth_client, db_session, test_org, monkeypatch
):
    monkeypatch.setattr("app.api.events.sign_gcs_url", _fake_signer)
    event = await _seed_event(db_session, test_org)

    resp = await auth_client.get(f"/api/events/{event.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_url"] == "https://signed.example/gs://bucket/snap.jpg"
    assert body["clip_url"] == "https://signed.example/gs://bucket/clip.mp4"


@pytest.mark.asyncio
async def test_sign_gcs_url_fails_soft_when_client_raises(monkeypatch):
    """If the underlying GCS client raises, sign_gcs_url returns the input URI
    unchanged so the API still works without GCP credentials."""

    # Reset the cached client so our monkeypatched factory takes effect.
    monkeypatch.setattr(gcs_service, "_client", None)

    def _raise(*args, **kwargs):
        raise RuntimeError("no credentials in test env")

    # Patch the lazy client factory to raise.
    monkeypatch.setattr(gcs_service, "_get_client", _raise)

    out = gcs_service.sign_gcs_url("gs://bucket/snap.jpg")
    assert out == "gs://bucket/snap.jpg"


@pytest.mark.asyncio
async def test_sign_gcs_url_passthrough_for_non_gs_uris():
    assert gcs_service.sign_gcs_url(None) is None
    assert gcs_service.sign_gcs_url("") == ""
    assert gcs_service.sign_gcs_url("https://cdn.example/x.jpg") == "https://cdn.example/x.jpg"
    assert gcs_service.sign_gcs_url("/local/path.jpg") == "/local/path.jpg"


@pytest.mark.asyncio
async def test_list_events_route_works_when_signing_fails(
    auth_client, db_session, test_org, monkeypatch
):
    """End-to-end: GCS client raises but the route still returns 200 with the
    raw gs:// URI thanks to the fail-soft behavior in sign_gcs_url."""

    monkeypatch.setattr(gcs_service, "_client", None)

    def _raise(*args, **kwargs):
        raise RuntimeError("no credentials in test env")

    monkeypatch.setattr(gcs_service, "_get_client", _raise)

    event = await _seed_event(db_session, test_org)

    resp = await auth_client.get(f"/api/events/{event.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_url"] == "gs://bucket/snap.jpg"
    assert body["clip_url"] == "gs://bucket/clip.mp4"
