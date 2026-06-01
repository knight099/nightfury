import pytest
import pytest_asyncio

from app.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _clear_paircode_rate(test_user):
    from app.core.redis import get_redis

    r = await get_redis()
    await r.delete(f"paircode:rate:{test_user.id}")
    yield
    await r.delete(f"paircode:rate:{test_user.id}")


@pytest.mark.asyncio
async def test_onboarding_full_flow(auth_client, client):
    # 1. Mint a pair code as authenticated user
    mint = await auth_client.post("/api/agents/pair-codes")
    assert mint.status_code == 201, mint.text
    code = mint.json()["code"]

    # 2. Redeem code via unauthenticated /pair endpoint
    pair_payload = {
        "code": code,
        "machine_id": "m12345678",
        "pubkey": "p" * 16,
        "version": "0.1.0",
    }
    pair_resp = await client.post("/api/agents/pair", json=pair_payload)
    assert pair_resp.status_code == 200, pair_resp.text
    pair = pair_resp.json()
    device_token = pair["device_token"]
    assert device_token
    assert pair["relay_url"]
    assert pair["org_id"]
    assert pair["agent_id"]

    # 3. Worker verifies the device token
    verify_resp = await client.post(
        "/internal/agents/verify-token",
        json={"token": device_token},
        headers={"X-Worker-Key": settings.worker_api_key},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    body = verify_resp.json()
    assert body["org_id"] == pair["org_id"]
    assert body["agent_id"] == pair["agent_id"]

    # 4. Listing as the authed user shows the new agent
    list_resp = await auth_client.get("/api/agents")
    assert list_resp.status_code == 200, list_resp.text
    agents = list_resp.json()["agents"]
    agent_ids = [a["id"] for a in agents]
    assert pair["agent_id"] in agent_ids
