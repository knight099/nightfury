"""
Server-side session management in Redis.
- Sessions stored in Redis, NOT in the token
- Token is just an encrypted pointer to the session
- Instant revocation (delete from Redis = logged out)
- Device-bound (IP + User-Agent fingerprint)
- Brute-force protection with account lockout
- Sliding expiry (1hr idle) + absolute expiry (24hr max)
"""
import time
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.core.redis import get_redis
from app.core.security import (
    encrypt_token,
    decrypt_token,
    generate_session_id,
    compute_device_fingerprint,
)

logger = logging.getLogger(__name__)

SESSION_IDLE_TTL = 3600       # 1 hour idle timeout
SESSION_MAX_TTL = 86400       # 24 hour absolute max
LOCKOUT_THRESHOLD = 5         # failed attempts before lockout
LOCKOUT_DURATION = 900        # 15 minutes lockout


class SessionManager:
    """Redis-backed session management."""

    async def create_session(
        self,
        user_id: str,
        username: str,
        role: str,
        org_id: str | None,
        ip: str,
        user_agent: str,
    ) -> str:
        """
        Create a new session. Returns an encrypted opaque token.
        """
        redis_client = await get_redis()
        session_id = generate_session_id()
        fingerprint = compute_device_fingerprint(ip, user_agent)
        now = time.time()

        session_data = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "org_id": org_id or "",
            "fingerprint": fingerprint,
            "created_at": now,
            "last_active": now,
            "ip": ip,
        }

        # Store session in Redis with TTL
        key = f"session:{session_id}"
        await redis_client.setex(key, SESSION_MAX_TTL, json.dumps(session_data))

        # Track active sessions per user (for admin visibility)
        await redis_client.sadd(f"user_sessions:{user_id}", session_id)
        await redis_client.expire(f"user_sessions:{user_id}", SESSION_MAX_TTL)

        # Generate encrypted token containing only the session_id
        token = encrypt_token({"sid": session_id, "t": int(now)})
        return token

    async def validate_session(
        self, token: str, ip: str, user_agent: str
    ) -> dict | None:
        """
        Validate a session token. Returns session data or None.
        Checks: decryption, existence, fingerprint, expiry.
        """
        # Decrypt token to get session_id
        payload = decrypt_token(token)
        if not payload or "sid" not in payload:
            return None

        session_id = payload["sid"]
        redis_client = await get_redis()
        key = f"session:{session_id}"

        # Load session from Redis
        raw = await redis_client.get(key)
        if not raw:
            return None

        session = json.loads(raw)

        # Check device fingerprint (session binding)
        expected_fingerprint = compute_device_fingerprint(ip, user_agent)
        if session["fingerprint"] != expected_fingerprint:
            logger.warning(
                f"Session fingerprint mismatch for user {session['username']} "
                f"(expected={session['fingerprint']}, got={expected_fingerprint})"
            )
            return None

        # Check idle timeout
        now = time.time()
        if now - session["last_active"] > SESSION_IDLE_TTL:
            await self.revoke_session(token)
            return None

        # Check absolute timeout
        if now - session["created_at"] > SESSION_MAX_TTL:
            await self.revoke_session(token)
            return None

        # Update last_active (sliding window)
        session["last_active"] = now
        remaining_ttl = int(SESSION_MAX_TTL - (now - session["created_at"]))
        if remaining_ttl > 0:
            await redis_client.setex(key, remaining_ttl, json.dumps(session))

        return session

    async def revoke_session(self, token: str):
        """Revoke a single session (logout)."""
        payload = decrypt_token(token)
        if not payload or "sid" not in payload:
            return

        session_id = payload["sid"]
        redis_client = await get_redis()
        key = f"session:{session_id}"

        # Get user_id before deleting
        raw = await redis_client.get(key)
        if raw:
            session = json.loads(raw)
            await redis_client.srem(f"user_sessions:{session['user_id']}", session_id)

        await redis_client.delete(key)

    async def revoke_all_user_sessions(self, user_id: str):
        """Revoke ALL sessions for a user (force logout everywhere)."""
        redis_client = await get_redis()
        session_ids = await redis_client.smembers(f"user_sessions:{user_id}")

        for sid in session_ids:
            await redis_client.delete(f"session:{sid}")

        await redis_client.delete(f"user_sessions:{user_id}")

    async def get_active_sessions(self, user_id: str) -> list[dict]:
        """List all active sessions for a user (admin feature)."""
        redis_client = await get_redis()
        session_ids = await redis_client.smembers(f"user_sessions:{user_id}")
        sessions = []

        for sid in session_ids:
            raw = await redis_client.get(f"session:{sid}")
            if raw:
                session = json.loads(raw)
                sessions.append({
                    "session_id": sid,
                    "ip": session.get("ip", ""),
                    "created_at": session.get("created_at", 0),
                    "last_active": session.get("last_active", 0),
                })

        return sessions

    # ─── Brute-force Protection ────────────────────────────────────────────

    async def record_failed_login(self, username: str, ip: str):
        """Record a failed login attempt."""
        redis_client = await get_redis()
        key = f"login_failures:{username}"
        count = await redis_client.incr(key)
        await redis_client.expire(key, LOCKOUT_DURATION)

        if count >= LOCKOUT_THRESHOLD:
            lockout_key = f"lockout:{username}"
            await redis_client.setex(lockout_key, LOCKOUT_DURATION, "1")
            logger.warning(f"Account locked: {username} (IP: {ip})")

    async def is_locked_out(self, username: str) -> bool:
        """Check if account is locked due to failed attempts."""
        redis_client = await get_redis()
        return await redis_client.exists(f"lockout:{username}")

    async def clear_failed_attempts(self, username: str):
        """Clear failed login count on successful login."""
        redis_client = await get_redis()
        await redis_client.delete(f"login_failures:{username}")


session_manager = SessionManager()
