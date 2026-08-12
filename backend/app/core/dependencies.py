import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.sessions import session_manager
from app.models.agent import Agent
from app.models.user import User
from app.services.agent_auth import resolve_agent_by_token


async def get_current_user(
    request: Request,
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate session token from Authorization header.
    Token is AES-256-GCM encrypted, session stored server-side in Redis.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization format",
        )

    token = authorization[7:]

    # Get client IP and User-Agent for session binding verification
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    # Validate session in Redis
    session = await session_manager.validate_session(token, ip, user_agent)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    # Load user from DB
    user_id = session["user_id"]
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id), User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled",
        )

    return user


async def get_agent_from_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """Resolve a paired Agent from a Bearer device token.

    Uses the indexed ``device_token_id`` lookup key so this costs one Argon2
    verify per request rather than one per agent row (see
    app.services.agent_auth).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    agent = await resolve_agent_by_token(db, token)
    if agent is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    return agent


async def verify_worker_key(
    request: Request,
    x_worker_key: str | None = Header(default=None, alias="X-Worker-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    """Verify worker API key or device-token Bearer for internal endpoints.

    Accepts either:
    1. X-Worker-Key header matching settings.worker_api_key (cloud Worker VM path)
    2. Authorization: Bearer <token> matching a paired Agent's device_token_hash (edge box path)

    On success, attaches request.state.internal_principal with auth mode details.
    """
    # Path 1: Check X-Worker-Key (cloud Worker VM)
    if x_worker_key and x_worker_key == settings.worker_api_key:
        request.state.internal_principal = {"kind": "worker"}
        return

    # Path 2: Check Bearer token (edge box with paired Agent).
    # Indexed lookup key + single Argon2 verify — this is the hot ingestion
    # path (/internal/events, /internal/heartbeat), so it must not scale
    # with the number of paired agents.
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        agent = await resolve_agent_by_token(db, token)
        if agent is not None:
            request.state.internal_principal = {
                "kind": "agent",
                "agent_id": agent.id,
                "org_id": agent.org_id,
            }
            return

    # Neither path succeeded
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid worker key or device token",
    )


# ─── RBAC Helpers ───────────────────────────────────────────────────────────
# Role hierarchy: super_admin > owner > admin > operator > viewer
# super_admin: god mode, bypasses everything
# owner: full control of their org (manage users, cameras, alerts, sites)
# admin: manage cameras, alerts, sites — cannot manage users
# operator: view all + submit event feedback — no config changes
# viewer: read-only, no mutations

ROLE_LEVELS = {
    "super_admin": 100,
    "owner": 80,
    "admin": 60,
    "operator": 40,
    "viewer": 20,
}


def require_role(user: User, minimum_role: str):
    """Raise 403 if user's role is below the minimum required."""
    user_level = ROLE_LEVELS.get(user.role, 0)
    required_level = ROLE_LEVELS.get(minimum_role, 0)
    if user_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {minimum_role} role or above",
        )
