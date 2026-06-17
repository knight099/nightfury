"""Tests for /api/cameras — CRUD + stream URL."""
import uuid

import pytest

from app.models.camera import Camera
from app.models.site import Site


def _make_site(org_id):
    return Site(org_id=org_id, name="Main Site", timezone="Asia/Kolkata")


@pytest.mark.asyncio
async def test_list_cameras_empty(auth_client):
    resp = await auth_client.get("/api/cameras")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_camera_rtsp(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    resp = await auth_client.post(
        "/api/cameras",
        json={
            "name": "Front Gate",
            "site_id": str(site.id),
            "ingest_mode": "rtsp_pull",
            "rtsp_url": "rtsp://10.0.0.5/stream1",
            "enabled_events": ["person", "vehicle"],
            "sensitivity": "medium",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    cam = body["camera"]
    assert cam["name"] == "Front Gate"
    assert cam["ingest_mode"] == "rtsp_pull"
    assert "id" in cam


@pytest.mark.asyncio
async def test_create_camera_rtmp_generates_stream_key(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    resp = await auth_client.post(
        "/api/cameras",
        json={
            "name": "Backyard",
            "site_id": str(site.id),
            "ingest_mode": "rtmp_push",
            "enabled_events": ["motion"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["stream_key"] is not None
    assert len(body["stream_key"]) > 8
    assert body["camera"]["ingest_mode"] == "rtmp_push"


@pytest.mark.asyncio
async def test_list_cameras_org_scoped(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="My Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add(cam)
    await db_session.flush()

    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_site = _make_site(other_org.id)
    db_session.add(other_site)
    await db_session.flush()

    other_cam = Camera(
        org_id=other_org.id,
        site_id=other_site.id,
        name="Their Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/y",
    )
    db_session.add(other_cam)
    await db_session.flush()

    resp = await auth_client.get("/api/cameras")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert str(cam.id) in ids
    assert str(other_cam.id) not in ids


@pytest.mark.asyncio
async def test_get_camera_detail(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="My Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add(cam)
    await db_session.flush()

    resp = await auth_client.get(f"/api/cameras/{cam.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(cam.id)


@pytest.mark.asyncio
async def test_get_camera_other_org_404(auth_client, db_session, test_org):
    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_site = _make_site(other_org.id)
    db_session.add(other_site)
    await db_session.flush()

    other_cam = Camera(
        org_id=other_org.id,
        site_id=other_site.id,
        name="Their Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/y",
    )
    db_session.add(other_cam)
    await db_session.flush()

    resp = await auth_client.get(f"/api/cameras/{other_cam.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_camera_name(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Old Name",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add(cam)
    await db_session.flush()

    resp = await auth_client.patch(f"/api/cameras/{cam.id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_camera(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="To Delete",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add(cam)
    await db_session.flush()

    resp = await auth_client.delete(f"/api/cameras/{cam.id}")
    assert resp.status_code == 204

    resp2 = await auth_client.get(f"/api/cameras/{cam.id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_stream_url_returns_signed_url(auth_client, db_session, test_org):
    site = _make_site(test_org.id)
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Stream Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add(cam)
    await db_session.flush()

    resp = await auth_client.get(f"/api/cameras/{cam.id}/stream-url")
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert "expires_at" in body
    assert str(cam.id) in body["url"]
    assert "token=" in body["url"]


@pytest.mark.asyncio
async def test_stream_url_other_org_404(auth_client, db_session, test_org):
    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_site = _make_site(other_org.id)
    db_session.add(other_site)
    await db_session.flush()

    other_cam = Camera(
        org_id=other_org.id,
        site_id=other_site.id,
        name="Their Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/z",
    )
    db_session.add(other_cam)
    await db_session.flush()

    resp = await auth_client.get(f"/api/cameras/{other_cam.id}/stream-url")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cameras_unauthenticated(client):
    # Required Authorization header missing → 422 Unprocessable Entity
    resp = await client.get("/api/cameras")
    assert resp.status_code == 422
