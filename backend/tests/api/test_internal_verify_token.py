import uuid

import pytest

from app.config import settings
from app.models.agent import Agent
from app.services.device_token_service import DeviceTokenService


@pytest.mark.asyncio
async def test_verify_token_valid(client, db_session, test_org):
    token, hashed = DeviceTokenService.mint()
    agent = Agent(
        org_id=test_org.id,
        machine_id=f"machine-{uuid.uuid4().hex[:8]}",
        pubkey="pk",
        device_token_hash=hashed,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    resp = await client.post(
        "/internal/agents/verify-token",
        json={"token": token},
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] == str(test_org.id)
    assert body["agent_id"] == str(agent.id)


@pytest.mark.asyncio
async def test_verify_token_invalid(client, db_session, test_org):
    _, hashed = DeviceTokenService.mint()
    agent = Agent(
        org_id=test_org.id,
        machine_id=f"machine-{uuid.uuid4().hex[:8]}",
        pubkey="pk",
        device_token_hash=hashed,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    resp = await client.post(
        "/internal/agents/verify-token",
        json={"token": "bogus"},
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert resp.status_code == 401
