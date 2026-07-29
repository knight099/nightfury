"""Super admin routes — full control over all tenants, users, passwords, sessions."""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import hash_password
from app.core.sessions import session_manager
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, UpdateUserRequest, UserResponse
from app.schemas.organization import CreateOrgRequest, OrgResponse, UpdateOrgRequest
from app.services.soft_delete_service import soft_delete_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_super_admin(user: User):
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")


@router.get("/orgs", response_model=list[OrgResponse])
async def list_all_orgs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    include_deleted: bool = Query(False),
):
    _require_super_admin(user)
    q = select(Organization)
    if not include_deleted:
        q = q.where(Organization.deleted_at.is_(None))
    result = await db.execute(q.order_by(Organization.created_at.desc()))
    return [OrgResponse.model_validate(o) for o in result.scalars().all()]


@router.post("/orgs", response_model=OrgResponse, status_code=201)
async def create_org(
    body: CreateOrgRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    slug = re.sub(r"[^\w\s-]", "", body.name.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-") + "-" + uuid.uuid4().hex[:6]

    org = Organization(
        name=body.name,
        slug=slug,
        plan=body.plan,
        settings=body.settings or {},
    )
    db.add(org)
    await db.flush()
    return OrgResponse.model_validate(org)


@router.get("/orgs/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrgResponse.model_validate(org)


@router.patch("/orgs/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: uuid.UUID,
    body: UpdateOrgRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    await db.flush()
    return OrgResponse.model_validate(org)


@router.delete("/orgs/{org_id}", status_code=204)
async def delete_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Organization already deleted")
    await soft_delete_service.delete_organization(org, db)


@router.post("/orgs/{org_id}/restore", response_model=OrgResponse)
async def restore_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.deleted_at is None:
        raise HTTPException(status_code=400, detail="Organization is not deleted")
    await soft_delete_service.restore_organization(org, db)
    return OrgResponse.model_validate(org)


@router.get("/users", response_model=list[UserResponse])
async def list_all_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = Query(None),
    role: str | None = Query(None),
    include_deleted: bool = Query(False),
):
    _require_super_admin(user)
    q = select(User)
    if org_id:
        q = q.where(User.org_id == org_id)
    if role:
        q = q.where(User.role == role)
    if not include_deleted:
        q = q.where(User.deleted_at.is_(None))
    result = await db.execute(q.order_by(User.created_at.desc()))
    return [UserResponse.model_validate(u) for u in result.scalars().all()]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(target)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    await db.flush()
    return UserResponse.model_validate(target)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "super_admin":
        raise HTTPException(status_code=400, detail="Cannot delete super admin")
    if target.deleted_at is not None:
        raise HTTPException(status_code=400, detail="User already deleted")
    await soft_delete_service.delete_user(target, db)


@router.post("/users/{user_id}/restore", response_model=UserResponse)
async def restore_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.deleted_at is None:
        raise HTTPException(status_code=400, detail="User is not deleted")
    await soft_delete_service.restore_user(target, db)
    return UserResponse.model_validate(target)


@router.post("/users/{user_id}/change-password", status_code=200)
async def change_user_password(
    user_id: uuid.UUID,
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.password_hash = hash_password(body.new_password)
    target.must_change_password = True
    await db.flush()
    return {"status": "ok", "message": f"Password changed for {target.username}"}


@router.post("/users/create", response_model=UserResponse, status_code=201)
async def admin_create_user(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a user in any org with any role."""
    _require_super_admin(user)

    username = body.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="username required")

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    new_user = User(
        org_id=body.get("org_id"),
        username=username,
        password_hash=hash_password(body.get("password", "changeme123")),
        name=body.get("name", username),
        role=body.get("role", "viewer"),
        is_active=body.get("is_active", True),
        must_change_password=body.get("must_change_password", True),
        sites_access=body.get("sites_access", []),
    )
    db.add(new_user)
    await db.flush()
    return UserResponse.model_validate(new_user)


@router.post("/users/{user_id}/force-logout", status_code=200)
async def force_logout_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Force logout a user from all devices (revoke all sessions)."""
    _require_super_admin(user)
    await session_manager.revoke_all_user_sessions(str(user_id))
    return {"status": "ok", "message": "All sessions revoked"}


@router.get("/users/{user_id}/sessions")
async def view_user_sessions(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """View all active sessions for any user."""
    _require_super_admin(user)
    sessions = await session_manager.get_active_sessions(str(user_id))
    return {"sessions": sessions}
