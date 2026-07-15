import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.sessions import session_manager
from app.models.agent import Agent
from app.models.user import User
from app.services.device_token_service import DeviceTokenService


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

    Performs a linear scan + Argon2 verify across non-unpaired agents.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    svc = DeviceTokenService()
    result = await db.execute(select(Agent).where(Agent.status != "unpaired"))
    for agent in result.scalars():
        if svc.verify(token, agent.device_token_hash):
            return agent
    raise HTTPException(status_code=401, detail="invalid device token")


async def verify_worker_key(
    x_worker_key: str | None = Header(default=None, alias="X-Worker-Key"),
):
    """Verify worker API key for internal endpoints."""
    if not x_worker_key or x_worker_key != settings.worker_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker key",
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
