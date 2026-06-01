import pytest
from sqlalchemy import select

from app.models.agent import Agent


@pytest.mark.asyncio
async def test_create_agent(db_session, test_org):
    agent = Agent(
        org_id=test_org.id,
        machine_id="abc123",
        pubkey="ed25519-pub",
        device_token_hash="$argon2id$...",
        version="0.1.0",
        status="unpaired",
    )
    db_session.add(agent)
    await db_session.flush()
    result = await db_session.execute(select(Agent).where(Agent.id == agent.id))
    fetched = result.scalar_one()
    assert fetched.machine_id == "abc123"
    assert fetched.status == "unpaired"


@pytest.mark.asyncio
async def test_unique_org_machine(db_session, test_org):
    db_session.add(
        Agent(
            org_id=test_org.id,
            machine_id="dup",
            pubkey="k",
            device_token_hash="h",
            status="online",
        )
    )
    await db_session.flush()
    db_session.add(
        Agent(
            org_id=test_org.id,
            machine_id="dup",
            pubkey="k2",
            device_token_hash="h2",
            status="online",
        )
    )
    with pytest.raises(Exception):
        await db_session.flush()
