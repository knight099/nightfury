import pytest

from app.models.agent import Agent


@pytest.mark.asyncio
async def test_list_agents_for_org(auth_client, db_session, test_org):
    db_session.add(
        Agent(
            org_id=test_org.id,
            machine_id="m-list-1",
            pubkey="pubkeyXXXXXXXXXXX",
            device_token_hash="hashXXXXXXXXXXXX",
            status="online",
            transport="grpc",
            version="0.1.0",
        )
    )
    await db_session.flush()

    resp = await auth_client.get("/api/agents")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "agents" in body
    assert len(body["agents"]) == 1
    assert body["agents"][0]["machine_id"] == "m-list-1"


@pytest.mark.asyncio
async def test_list_agents_unauthenticated(client):
    resp = await client.get("/api/agents")
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_super_admin_sees_all_agents(admin_client, db_session, test_org):
    db_session.add(
        Agent(
            org_id=test_org.id,
            machine_id="m-admin-1",
            pubkey="pubkeyXXXXXXXXXXX",
            device_token_hash="hashXXXXXXXXXXXX",
            status="online",
        )
    )
    await db_session.flush()
    resp = await admin_client.get("/api/agents")
    assert resp.status_code == 200
    assert len(resp.json()["agents"]) >= 1
