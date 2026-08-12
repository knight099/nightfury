import uuid

import pytest
from fastapi import HTTPException

from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.services.device_token_service import DeviceTokenService


@pytest.mark.asyncio
async def test_valid_token_returns_agent(db_session, test_org):
    token, hashed, _ = DeviceTokenService.mint()
    agent = Agent(
        org_id=test_org.id,
        machine_id=f"machine-{uuid.uuid4().hex[:8]}",
        pubkey="pk",
        device_token_hash=hashed,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    got = await get_agent_from_token(
        authorization=f"Bearer {token}", db=db_session
    )
    assert got.id == agent.id
    assert got.org_id == test_org.id


@pytest.mark.asyncio
async def test_missing_header_raises_401(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_agent_from_token(authorization=None, db=db_session)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_bad_token_raises_401(db_session, test_org):
    _, hashed, _ = DeviceTokenService.mint()
    agent = Agent(
        org_id=test_org.id,
        machine_id=f"machine-{uuid.uuid4().hex[:8]}",
        pubkey="pk",
        device_token_hash=hashed,
        status="active",
    )
    db_session.add(agent)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_agent_from_token(
            authorization="Bearer not-the-real-token", db=db_session
        )
    assert exc.value.status_code == 401
