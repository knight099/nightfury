"""Redis sliding-window rate limiting.

Provides:
- ``check_rate_limit``: low-level helper using a Redis sorted-set sliding window.
- ``RateLimitMiddleware``: Starlette middleware that maps incoming requests to
  ``(limit, window)`` tuples and enforces them. Fail-open on Redis errors.
"""
from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from typing import Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def check_rate_limit(
    redis_client,
    key: str,
    limit: int,
    window_seconds: int,
) -> Tuple[bool, int]:
    """Sliding-window rate limit check.

    Records the current request in a Redis sorted-set keyed by ``key`` (score =
    now in milliseconds). Trims entries older than ``window_seconds`` and counts
    the remaining members. If the count exceeds ``limit``, returns
    ``(False, retry_after_seconds)`` where ``retry_after_seconds`` is the time
    until the oldest in-window entry ages out (>=1).

    On allow: returns ``(True, 0)``.
    """
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000
    cutoff = now_ms - window_ms
    # Unique member to avoid score collisions on burst traffic.
    member = f"{now_ms}-{uuid.uuid4().hex}"

    pipe = redis_client.pipeline(transaction=False)
    pipe.zremrangebyscore(key, 0, cutoff)
    pipe.zadd(key, {member: now_ms})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 1)
    results = await pipe.execute()
    count = int(results[2])

    if count > limit:
        # Look up oldest score still in the window to compute retry-after.
        oldest = await redis_client.zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_score = int(oldest[0][1])
            retry_ms = (oldest_score + window_ms) - now_ms
            retry_after = max(1, math.ceil(retry_ms / 1000))
        else:
            retry_after = 1
        return False, retry_after

    return True, 0


# Per-route rate-limit configuration. Order matters: first match wins.
# Each entry: (method or "*", path, limit, window_seconds, scope)
# scope: "ip" -> key by client IP, "session" -> key by bearer-token tail
_ROUTE_RULES: list[tuple[str, str, int, int, str]] = [
    ("POST", "/api/auth/login", 10, 60, "ip"),
    ("POST", "/api/auth/signup", 5, 3600, "ip"),
    ("POST", "/api/agents/pair", 20, 3600, "ip"),
    # The six-digit code space (and claim_token guesses) is only meaningful
    # if the endpoint can't be walked — rate-limit by IP, not by bearer
    # token, since a script could rotate/omit auth but not source IP as
    # easily.
    ("POST", "/api/devices/claim", 10, 60, "ip"),
    # Unauthenticated: each call writes a Redis claim_token (256-bit, 10min
    # TTL) plus a Postgres row. A legitimate device calls this once at boot
    # (and again only if it reboots or its request is refreshed); bound it
    # well above that to avoid false positives behind carrier-grade NAT
    # while still capping unauthenticated write amplification.
    ("POST", "/api/devices/provision", 30, 3600, "ip"),
]

# Catch-all for authenticated API traffic.
_AUTHENTICATED_API_LIMIT = 120
_AUTHENTICATED_API_WINDOW = 60


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _token_tail_hash(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def _resolve_rules(request: Request) -> list[Tuple[str, int, int]]:
    """Return the (key, limit, window) rules to enforce for this request.

    Usually a single rule, but an explicit per-route rule and the
    account-level catch-all are BOTH applied when the caller is
    authenticated: an IP-scoped route rule exists to stop an endpoint being
    walked by an anonymous/rotating-identity script, and must not, as a side
    effect, exempt an authenticated caller from the token-keyed ceiling it
    would otherwise be subject to (IP is attacker-controlled via
    X-Forwarded-For; the bearer-token hash is not).
    """
    path = request.url.path
    method = request.method.upper()

    # Skip exempt paths.
    if path.startswith("/internal/"):
        return []
    if path.startswith("/ws/"):
        return []
    if path == "/health":
        return []

    rules: list[Tuple[str, int, int]] = []

    # Explicit per-route rules (IP-scoped, or session-scoped falling back to IP).
    for rule_method, rule_path, limit, window, scope in _ROUTE_RULES:
        if rule_path == path and (rule_method == "*" or rule_method == method):
            if scope == "ip":
                key = f"rl:{rule_path}:ip:{_client_ip(request)}"
            else:
                tail = _token_tail_hash(request)
                if tail is None:
                    key = f"rl:{rule_path}:ip:{_client_ip(request)}"
                else:
                    key = f"rl:{rule_path}:tok:{tail}"
            rules.append((key, limit, window))
            break

    # Authenticated /api/* traffic is always additionally subject to the
    # account-level catch-all, even when an explicit per-route rule above
    # already matched.
    if path.startswith("/api/"):
        tail = _token_tail_hash(request)
        if tail is not None:
            key = f"rl:api:tok:{tail}"
            if not any(existing_key == key for existing_key, _, _ in rules):
                rules.append((key, _AUTHENTICATED_API_LIMIT, _AUTHENTICATED_API_WINDOW))
        elif not rules:
            # Unauthenticated /api/* call with no specific rule: skip
            # (per-route rules above already cover login/signup).
            return []

    return rules


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-route Redis sliding-window rate limits.

    Fails open: any error talking to Redis is logged and the request proceeds.
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        rules = _resolve_rules(request)
        if not rules:
            return await call_next(request)

        try:
            redis_client = await get_redis()
        except Exception:
            request_id = getattr(request.state, "request_id", "-")
            logger.warning(
                "rate_limit_check_failed request_id=%s (redis unavailable)",
                request_id, exc_info=True,
            )
            return await call_next(request)

        # Every applicable rule must pass — a route-specific rule and the
        # account-level catch-all are independent ceilings, not alternatives.
        for key, limit, window in rules:
            try:
                allowed, retry_after = await check_rate_limit(
                    redis_client, key, limit, window
                )
            except Exception:
                request_id = getattr(request.state, "request_id", "-")
                logger.warning(
                    "rate_limit_check_failed request_id=%s key=%s", request_id, key,
                    exc_info=True,
                )
                continue

            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )

        return await call_next(request)
