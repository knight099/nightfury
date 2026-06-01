import pytest


@pytest.mark.asyncio
async def test_pair_valid_code(auth_client, client):
    mint = await auth_client.post("/api/agents/pair-codes")
    assert mint.status_code == 201
    code = mint.json()["code"]

    payload = {
        "code": code,
        "machine_id": "machine-abc-123",
        "pubkey": "ssh-ed25519 AAAAfakekey0000",
        "version": "0.1.0",
    }
    resp = await client.post("/api/agents/pair", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["device_token"]
    assert body["relay_url"]
    assert body["org_id"]
    assert body["agent_id"]


@pytest.mark.asyncio
async def test_pair_unknown_code(client):
    payload = {
        "code": "999999",
        "machine_id": "machine-abc-123",
        "pubkey": "ssh-ed25519 AAAAfakekey0000",
    }
    resp = await client.post("/api/agents/pair", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pair_consumed_code_is_rejected(auth_client, client):
    mint = await auth_client.post("/api/agents/pair-codes")
    code = mint.json()["code"]
    payload = {
        "code": code,
        "machine_id": "machine-abc-123",
        "pubkey": "ssh-ed25519 AAAAfakekey0000",
    }
    first = await client.post("/api/agents/pair", json=payload)
    assert first.status_code == 200
    payload2 = dict(payload, machine_id="machine-xyz-999")
    second = await client.post("/api/agents/pair", json=payload2)
    assert second.status_code == 400
