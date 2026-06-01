"""Tests for GET /internal/assignments — worker camera assignment endpoint."""
import uuid

import pytest

from app.config import settings
from app.models.camera import Camera
from app.models.site import Site


@pytest.mark.asyncio
async def test_assignments_returns_rtsp_and_rtmp_cameras(client, db_session, test_org):
    site = Site(org_id=test_org.id, name="HQ", timezone="Asia/Kolkata")
    db_session.add(site)
    await db_session.flush()

    rtsp_cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Front Door",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://10.0.0.5/stream1",
        enabled_events=["person", "vehicle"],
        detection_zones=[{"name": "porch", "polygon": [[0, 0], [1, 0], [1, 1]]}],
        sensitivity="high",
        idle_fps=1.0,
        active_fps=5.0,
    )
    rtmp_cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Backyard",
        ingest_mode="rtmp_push",
        stream_key=f"key-{uuid.uuid4().hex[:8]}",
        enabled_events=["motion"],
        detection_zones=[],
        sensitivity="medium",
        idle_fps=0.5,
        active_fps=3.0,
    )
    db_session.add_all([rtsp_cam, rtmp_cam])
    await db_session.flush()

    resp = await client.get(
        "/internal/assignments",
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "assignments" in body
    assert len(body["assignments"]) == 2

    by_id = {a["camera_id"]: a for a in body["assignments"]}
    rtsp = by_id[str(rtsp_cam.id)]
    assert rtsp["ingest_mode"] == "rtsp_pull"
    assert rtsp["rtsp_url"] == "rtsp://10.0.0.5/stream1"
    assert rtsp["stream_key"] is None
    assert rtsp["enabled_events"] == ["person", "vehicle"]
    assert rtsp["detection_zones"][0]["name"] == "porch"
    assert rtsp["sensitivity"] == "high"
    assert rtsp["idle_fps"] == 1.0
    assert rtsp["active_fps"] == 5.0
    assert rtsp["org_id"] == str(test_org.id)
    assert rtsp["name"] == "Front Door"
    assert rtsp["timezone"] == test_org.timezone

    rtmp = by_id[str(rtmp_cam.id)]
    assert rtmp["ingest_mode"] == "rtmp_push"
    assert rtmp["rtsp_url"] is None
    assert rtmp["stream_key"] == rtmp_cam.stream_key


@pytest.mark.asyncio
async def test_assignments_excludes_srt_push(client, db_session, test_org):
    site = Site(org_id=test_org.id, name="HQ", timezone="UTC")
    db_session.add(site)
    await db_session.flush()

    srt_cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="SRT Cam",
        ingest_mode="srt_push",
        stream_key=f"srt-{uuid.uuid4().hex[:8]}",
    )
    rtsp_cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="RTSP Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://example/x",
    )
    db_session.add_all([srt_cam, rtsp_cam])
    await db_session.flush()

    resp = await client.get(
        "/internal/assignments",
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert resp.status_code == 200
    ids = [a["camera_id"] for a in resp.json()["assignments"]]
    assert str(rtsp_cam.id) in ids
    assert str(srt_cam.id) not in ids


@pytest.mark.asyncio
async def test_assignments_empty_list(client, db_session, test_org):
    resp = await client.get(
        "/internal/assignments",
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert resp.status_code == 200
    assert resp.json() == {"assignments": []}


@pytest.mark.asyncio
async def test_assignments_missing_worker_key(client):
    resp = await client.get("/internal/assignments")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_assignments_wrong_worker_key(client):
    resp = await client.get(
        "/internal/assignments",
        headers={"X-Worker-Key": "totally-wrong-key"},
    )
    assert resp.status_code == 401
