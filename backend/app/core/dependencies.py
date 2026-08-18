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
    request.state.session = session

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


# ─── Site scoping ───────────────────────────────────────────────────────────
# `users.sites_access` has existed since the initial schema but was written and
# never read: every query filtered on `org_id` alone. On a single-site customer
# that was invisible; on a multi-site one it means a floor manager scoped to
# one building sees every camera and every event across the whole estate.
#
# The empty list deliberately means "unrestricted", not "nothing". Nothing has
# ever written a non-empty value, so treating empty as deny-all would lock out
# every existing account the moment enforcement was switched on. Restriction is
# opt-in per user; absence of a restriction is the status quo.


def permitted_site_ids(user: User) -> list[uuid.UUID] | None:
    """Sites this user may see, or ``None`` for unrestricted.

    ``None`` and ``[]`` are NOT interchangeable here — ``None`` is "apply no
    filter", while an empty list returned to a caller would mean "match
    nothing". Callers must check for ``None`` explicitly.
    """
    if user.role == "super_admin":
        return None
    if not user.sites_access:
        return None
    return list(user.sites_access)


def scope_to_sites(query, site_column, user: User):
    """Apply the caller's site restriction to ``query``, if they have one.

    ``site_column`` is whichever model's ``site_id`` the query selects from
    (``Event.site_id``, ``Camera.site_id``, ``Site.id``, …), so one helper
    covers every table that carries site ownership.
    """
    site_ids = permitted_site_ids(user)
    if site_ids is None:
        return query
    return query.where(site_column.in_(site_ids))


def user_may_access_site(user: User, site_id: uuid.UUID | None) -> bool:
    """Whether a single site is within the caller's scope.

    For the paths that hold one object rather than building a query — the
    WebSocket fan-out, and any per-row check after a fetch.
    """
    site_ids = permitted_site_ids(user)
    if site_ids is None:
        return True
    return site_id in site_ids
