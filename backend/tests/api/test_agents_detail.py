import uuid

import pytest

from app.models.agent import Agent
from app.models.camera import Camera
from app.models.site import Site


@pytest.mark.asyncio
async def test_get_agent_detail_with_streaming_count(auth_client, db_session, test_org):
    site = Site(org_id=test_org.id, name="Main")
    db_session.add(site)
    await db_session.flush()

    agent = Agent(
        org_id=test_org.id,
        machine_id="m-det-1",
        pubkey="pubkeyXXXXXXXXXXX",
        device_token_hash="hashXXXXXXXXXXXX",
        status="online",
    )
    db_session.add(agent)
    await db_session.flush()

    db_session.add_all([
        Camera(
            org_id=test_org.id,
            site_id=site.id,
            agent_id=agent.id,
            name="cam-online",
            ingest_mode="rtsp_pull",
            rtsp_url="rtsp://x/1",
            status="online",
        ),
        Camera(
            org_id=test_org.id,
            site_id=site.id,
            agent_id=agent.id,
            name="cam-offline",
            ingest_mode="rtsp_pull",
            rtsp_url="rtsp://x/2",
            status="offline",
        ),
    ])
    await db_session.flush()

    resp = await auth_client.get(f"/api/agents/{agent.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["machine_id"] == "m-det-1"
    assert body["cameras_streaming"] == 1


@pytest.mark.asyncio
async def test_get_agent_other_org_returns_404(auth_client, db_session):
    from app.models.organization import Organization

    other = Organization(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    await db_session.flush()
    agent = Agent(
        org_id=other.id,
        machine_id="m-other",
        pubkey="pubkeyXXXXXXXXXXX",
        device_token_hash="hashXXXXXXXXXXXX",
        status="online",
    )
    db_session.add(agent)
    await db_session.flush()

    resp = await auth_client.get(f"/api/agents/{agent.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_discover_returns_empty_list(auth_client, db_session, test_org):
    agent = Agent(
        org_id=test_org.id,
        machine_id="m-disc",
        pubkey="pubkeyXXXXXXXXXXX",
        device_token_hash="hashXXXXXXXXXXXX",
        status="online",
    )
    db_session.add(agent)
    await db_session.flush()

    resp = await auth_client.post(f"/api/agents/{agent.id}/discover")
    assert resp.status_code == 200
    assert resp.json() == {"cameras": []}


@pytest.mark.asyncio
async def test_register_camera_for_agent(auth_client, db_session, test_org):
    site = Site(org_id=test_org.id, name="Main")
    db_session.add(site)
    agent = Agent(
        org_id=test_org.id,
        machine_id="m-reg",
        pubkey="pubkeyXXXXXXXXXXX",
        device_token_hash="hashXXXXXXXXXXXX",
        status="online",
    )
    db_session.add(agent)
    await db_session.flush()

    resp = await auth_client.post(
        f"/api/agents/{agent.id}/cameras",
        json={
            "name": "Front Door",
            "site_id": str(site.id),
            "rtsp_url": "rtsp://192.168.1.10:554/cam/realmonitor",
            "brand": "cp_plus",
        },
    )
    assert resp.status_code == 201, resp.text
    cam_id = resp.json()["camera_id"]

    cam = await db_session.get(Camera, uuid.UUID(cam_id))
    assert cam is not None
    assert cam.agent_id == agent.id
    assert cam.org_id == test_org.id
    assert cam.rtsp_url == "rtsp://192.168.1.10:554/cam/realmonitor"


@pytest.mark.asyncio
async def test_register_camera_rejects_foreign_site(auth_client, db_session, test_org):
    from app.models.organization import Organization

    other = Organization(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    await db_session.flush()
    foreign_site = Site(org_id=other.id, name="Far")
    agent = Agent(
        org_id=test_org.id,
        machine_id="m-reg2",
        pubkey="pubkeyXXXXXXXXXXX",
        device_token_hash="hashXXXXXXXXXXXX",
        status="online",
    )
    db_session.add_all([foreign_site, agent])
    await db_session.flush()

    resp = await auth_client.post(
        f"/api/agents/{agent.id}/cameras",
        json={
            "name": "X",
            "site_id": str(foreign_site.id),
            "rtsp_url": "rtsp://x/y",
        },
    )
    assert resp.status_code == 400
