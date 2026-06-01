import pytest

from app.models.agent import Agent
from app.models.camera import Camera
from app.models.site import Site


@pytest.mark.asyncio
async def test_camera_links_to_agent(db_session, test_org):
    agent = Agent(
        org_id=test_org.id,
        machine_id="m1",
        pubkey="p",
        device_token_hash="h",
        status="online",
    )
    db_session.add(agent)

    site = Site(org_id=test_org.id, name="Main Site")
    db_session.add(site)
    await db_session.flush()

    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="cam1",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://x",
        agent_id=agent.id,
    )
    db_session.add(cam)
    await db_session.flush()
    assert cam.agent_id == agent.id
