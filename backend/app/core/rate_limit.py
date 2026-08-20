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


def _resolve_rule(request: Request) -> Optional[Tuple[str, int, int]]:
    """Return (key, limit, window) for the request, or None to skip."""
    path = request.url.path
    method = request.method.upper()

    # Skip exempt paths.
    if path.startswith("/internal/"):
        return None
    if path.startswith("/ws/"):
        return None
    if path == "/health":
        return None

    # Explicit per-route rules (IP-scoped).
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
            return key, limit, window

    # Default: authenticated /api/* traffic, keyed by bearer token tail.
    if path.startswith("/api/"):
        tail = _token_tail_hash(request)
        if tail is None:
            # Unauthenticated /api/* call without a specific rule: skip
            # (per-route rules above already cover login/signup).
            return None
        key = f"rl:api:tok:{tail}"
        return key, _AUTHENTICATED_API_LIMIT, _AUTHENTICATED_API_WINDOW

    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-route Redis sliding-window rate limits.

    Fails open: any error talking to Redis is logged and the request proceeds.
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        rule = _resolve_rule(request)
        if rule is None:
            return await call_next(request)

        key, limit, window = rule
        try:
            redis_client = await get_redis()
            allowed, retry_after = await check_rate_limit(
                redis_client, key, limit, window
            )
        except Exception:
            request_id = getattr(request.state, "request_id", "-")
            logger.warning(
                "rate_limit_check_failed request_id=%s key=%s", request_id, key,
                exc_info=True,
            )
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
