"""Tests for the Redis sliding-window rate limiter."""
from __future__ import annotations

import uuid

import pytest

from app.core import redis as redis_module
from app.core.rate_limit import check_rate_limit


@pytest.mark.asyncio
async def test_check_rate_limit_allows_under_limit_then_blocks():
    redis_client = await redis_module.get_redis()
    key = f"test:rl:{uuid.uuid4().hex}"

    for i in range(5):
        allowed, retry = await check_rate_limit(redis_client, key, limit=5, window_seconds=10)
        assert allowed is True, f"call {i} should be allowed"
        assert retry == 0

    allowed, retry = await check_rate_limit(redis_client, key, limit=5, window_seconds=10)
    assert allowed is False
    assert retry > 0
    assert retry <= 10


@pytest.fixture
def _enable_rate_limit():
    from app.config import settings
    prev = settings.rate_limit_enabled
    settings.rate_limit_enabled = True
    yield
    settings.rate_limit_enabled = prev


@pytest.mark.asyncio
async def test_login_endpoint_rate_limited(client, _enable_rate_limit):
    """Hitting /api/auth/login 10x is allowed, 11th is 429 from middleware."""
    # Use a unique IP so we don't collide with other tests' keys in Redis.
    ip = f"203.0.113.{uuid.uuid4().hex[:6]}"

    # Pre-clear any stale entries for this key.
    redis_client = await redis_module.get_redis()
    await redis_client.delete(f"rl:/api/auth/login:ip:{ip}")

    # Use a different username on each call to avoid the auth-layer
    # account-lockout 429 (which fires after 5 failures on the SAME username).
    for i in range(10):
        resp = await client.post(
            "/api/auth/login",
            json={"username": f"nobody-{uuid.uuid4().hex[:8]}", "password": "nope"},
            headers={"X-Forwarded-For": ip},
        )
        assert resp.status_code != 429, (
            f"call {i} unexpectedly rate-limited: {resp.status_code} {resp.text}"
        )

    # The 11th request from the same IP should be blocked by the rate-limit
    # middleware regardless of username.
    resp = await client.post(
        "/api/auth/login",
        json={"username": f"nobody-{uuid.uuid4().hex[:8]}", "password": "nope"},
        headers={"X-Forwarded-For": ip},
    )
    assert resp.status_code == 429
    assert resp.json() == {"detail": "rate limit exceeded"}
    assert "retry-after" in {h.lower() for h in resp.headers.keys()}
    assert int(resp.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_unavailable(client, monkeypatch):
    async def boom():
        raise RuntimeError("redis is down")

    from app.core import rate_limit as rl_module

    monkeypatch.setattr(rl_module, "get_redis", boom)

    resp = await client.post(
        "/api/auth/login",
        json={"username": f"nobody-{uuid.uuid4().hex[:8]}", "password": "nope"},
        headers={"X-Forwarded-For": "192.0.2.1"},
    )
    # Must NOT be 429 — fail-open. Auth failure is fine.
    assert resp.status_code != 429
