import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.security import hash_password, verify_password, needs_rehash
from app.core.sessions import session_manager
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import (
    InviteRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    # Check lockout
    if await session_manager.is_locked_out(body.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account locked due to too many failed attempts. Try again in 15 minutes.",
        )

    # Find user
    result = await db.execute(
        select(User).where(User.username == body.username, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        # Record failure
        await session_manager.record_failed_login(body.username, ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Rehash password if needed (algorithm upgrade)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    # Clear failed attempts
    await session_manager.clear_failed_attempts(body.username)

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.flush()

    # Create session
    token = await session_manager.create_session(
        user_id=str(user.id),
        username=user.username,
        role=user.role,
        org_id=str(user.org_id) if user.org_id else None,
        ip=ip,
        user_agent=user_agent,
    )

    return TokenResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Validate username format
    if not re.match(r"^[a-zA-Z0-9_.-]{3,50}$", body.username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-50 characters: letters, numbers, _, ., -",
        )

    # Check uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Validate password strength
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Create org
    org = Organization(
        name=body.org_name,
        slug=slugify(body.org_name) + "-" + uuid.uuid4().hex[:6],
    )
    db.add(org)
    await db.flush()

    # Create user
    user = User(
        org_id=org.id,
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        role="owner",
    )
    db.add(user)
    await db.flush()

    # Create session
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    token = await session_manager.create_session(
        user_id=str(user.id),
        username=user.username,
        role=user.role,
        org_id=str(org.id),
        ip=ip,
        user_agent=user_agent,
    )

    return TokenResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/logout", status_code=200)
async def logout(request: Request, user: User = Depends(get_current_user)):
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        await session_manager.revoke_session(token)
    return {"status": "ok"}


@router.post("/logout-all", status_code=200)
async def logout_all(user: User = Depends(get_current_user)):
    """Revoke ALL sessions for this user (logout from all devices)."""
    await session_manager.revoke_all_user_sessions(str(user.id))
    return {"status": "ok", "message": "All sessions revoked"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse.model_validate(user)


@router.get("/sessions")
async def list_sessions(user: User = Depends(get_current_user)):
    """List all active sessions for current user."""
    sessions = await session_manager.get_active_sessions(str(user.id))
    return {"sessions": sessions}


@router.post("/change-password", status_code=200)
async def change_own_password(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """User changes their own password (required after admin-set one-time password)."""
    body = await request.json()
    new_password = body.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await db.flush()

    return {"status": "ok", "message": "Password changed successfully"}


@router.post("/invite", response_model=UserResponse, status_code=201)
async def invite_user(
    body: InviteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "owner")

    if not re.match(r"^[a-zA-Z0-9_.-]{3,50}$", body.username):
        raise HTTPException(status_code=400, detail="Invalid username format")

    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    org_id = user.org_id
    if user.role == "super_admin" and not org_id:
        raise HTTPException(status_code=400, detail="Super admin must specify org context")

    new_user = User(
        org_id=org_id,
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
        must_change_password=True,
        sites_access=body.sites_access or [],
    )
    db.add(new_user)
    await db.flush()
    return UserResponse.model_validate(new_user)
