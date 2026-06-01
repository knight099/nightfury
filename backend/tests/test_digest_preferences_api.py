import pytest


@pytest.mark.asyncio
async def test_get_preferences_creates_defaults_if_missing(auth_client):
    resp = await auth_client.get("/api/digests/preferences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["morning_enabled"] is True
    assert body["morning_local_time"] == "07:00:00"


@pytest.mark.asyncio
async def test_update_preferences_persists(auth_client):
    resp = await auth_client.put(
        "/api/digests/preferences",
        json={"morning_enabled": False, "evening_local_time": "20:30:00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["morning_enabled"] is False
    assert body["evening_local_time"] == "20:30:00"

    resp = await auth_client.get("/api/digests/preferences")
    assert resp.json()["morning_enabled"] is False
