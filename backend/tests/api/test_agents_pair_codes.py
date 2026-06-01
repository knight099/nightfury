import re

import pytest


@pytest.mark.asyncio
async def test_create_pair_code_authenticated(auth_client):
    resp = await auth_client.post("/api/agents/pair-codes")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert re.fullmatch(r"\d{6}", body["code"])
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_create_pair_code_unauthenticated(client):
    resp = await client.post("/api/agents/pair-codes")
    # Missing Authorization header — FastAPI returns 422 for required Header(...)
    # while a malformed token would yield 401. Accept both as "not authenticated".
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_create_pair_code_super_admin_without_org(admin_client):
    resp = await admin_client.post("/api/agents/pair-codes")
    assert resp.status_code == 400
