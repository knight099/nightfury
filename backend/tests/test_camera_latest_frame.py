"""Tests for the camera latest-frame endpoint."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.camera import Camera
from app.models.organization import Organization
from app.models.site import Site


async def _seed_camera(db_session, org):
    site = Site(org_id=org.id, name="Site 1")
    db_session.add(site)
    await db_session.flush()

    camera = Camera(
        org_id=org.id,
        site_id=site.id,
        name="Cam 1",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example.local/stream",
    )
    db_session.add(camera)
    await db_session.flush()
    return camera


@pytest.mark.asyncio
async def test_latest_frame_happy_path(auth_client, db_session, test_org, monkeypatch):
    camera = await _seed_camera(db_session, test_org)
    fixed = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "app.api.cameras.gcs_blob_updated_at", lambda uri: fixed
    )
    monkeypatch.setattr(
        "app.api.cameras.sign_gcs_url",
        lambda uri, expires_in=None: f"https://signed.example/{uri}?ttl={expires_in}",
    )

    resp = await auth_client.get(f"/api/cameras/{camera.id}/latest-frame")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "url" in body and "updated_at" in body
    assert body["url"].startswith("https://signed.example/gs://")
    assert str(camera.id) in body["url"]
    assert "ttl=300" in body["url"]
    assert body["updated_at"].startswith("2026-05-29T12:00:00")


@pytest.mark.asyncio
async def test_latest_frame_missing_blob_returns_404(
    auth_client, db_session, test_org, monkeypatch
):
    camera = await _seed_camera(db_session, test_org)
    monkeypatch.setattr("app.api.cameras.gcs_blob_updated_at", lambda uri: None)

    resp = await auth_client.get(f"/api/cameras/{camera.id}/latest-frame")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no recent frame"


@pytest.mark.asyncio
async def test_latest_frame_camera_not_found(auth_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.cameras.gcs_blob_updated_at",
        lambda uri: datetime.now(timezone.utc),
    )
    missing_id = uuid.uuid4()
    resp = await auth_client.get(f"/api/cameras/{missing_id}/latest-frame")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Camera not found"


@pytest.mark.asyncio
async def test_latest_frame_other_org_camera_not_found(
    auth_client, db_session, monkeypatch
):
    """A camera that belongs to a different org should appear as 404 to a
    non-super_admin user (tenant isolation)."""
    other_org = Organization(name="Other Org", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other_org)
    await db_session.flush()

    camera = await _seed_camera(db_session, other_org)
    monkeypatch.setattr(
        "app.api.cameras.gcs_blob_updated_at",
        lambda uri: datetime.now(timezone.utc),
    )

    resp = await auth_client.get(f"/api/cameras/{camera.id}/latest-frame")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Camera not found"
