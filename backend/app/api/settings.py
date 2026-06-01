"""Org settings routes — owners manage their own org and team."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.security import hash_password
from app.core.sessions import session_manager
from app.models.ai_usage import AIUsage
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.organization import OrgResponse, UpdateOrgRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/org", response_model=OrgResponse)
async def get_my_org(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get current user's organization details."""
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No organization associated")
    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrgResponse.model_validate(org)


@router.patch("/org", response_model=OrgResponse)
async def update_my_org(
    body: UpdateOrgRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update own organization (owner only)."""
    require_role(user, "owner")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No organization associated")

    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    await db.flush()
    return OrgResponse.model_validate(org)


@router.get("/team", response_model=list[UserResponse])
async def list_team(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List users in own organization. Viewers only see other viewers."""
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No organization associated")

    q = select(User).where(User.org_id == user.org_id)
    if user.role == "viewer":
        q = q.where(User.role == "viewer")
    result = await db.execute(q.order_by(User.created_at.desc()))
    return [UserResponse.model_validate(u) for u in result.scalars().all()]


@router.patch("/team/{user_id}", response_model=UserResponse)
async def update_team_member(
    user_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a team member's role or active status (owner only)."""
    require_role(user, "owner")

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your org")

    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot modify yourself here")

    allowed_fields = {"name", "role", "is_active"}
    for field, value in body.items():
        if field in allowed_fields:
            if field == "role" and value not in ("admin", "operator", "viewer"):
                raise HTTPException(status_code=400, detail="Can only assign admin, operator, or viewer roles")
            setattr(target, field, value)
    await db.flush()
    return UserResponse.model_validate(target)


@router.delete("/team/{user_id}", status_code=204)
async def remove_team_member(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a user from own organization (owner only)."""
    require_role(user, "owner")

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your org")

    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    if target.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove another owner")

    await session_manager.revoke_all_user_sessions(str(target.id))
    await db.delete(target)


@router.post("/team/{user_id}/reset-password", status_code=200)
async def reset_team_member_password(
    user_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reset a team member's password (owner only). Sets must_change_password."""
    require_role(user, "owner")

    new_password = body.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    result = await db.execute(
        select(User).where(User.id == user_id, User.org_id == user.org_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found in your org")

    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    await db.flush()
    await session_manager.revoke_all_user_sessions(str(target.id))
    return {"status": "ok", "message": f"Password reset for {target.username}"}


# ── AI Usage Reporting (owner) ──────────────────────────────────────────────


@router.get("/ai-usage")
async def org_ai_usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
):
    """Org-wide AI usage report — owner only. Returns aggregate, per-user breakdown, recent calls."""
    require_role(user, "owner")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No organization associated")

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Aggregate
    agg_q = select(
        func.count(AIUsage.id).label("calls"),
        func.coalesce(func.sum(AIUsage.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(AIUsage.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AIUsage.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(AIUsage.cost_usd), 0.0).label("cost_usd"),
        func.coalesce(func.avg(AIUsage.latency_ms), 0).label("avg_latency_ms"),
    ).where(AIUsage.org_id == user.org_id, AIUsage.timestamp >= since)
    agg_row = (await db.execute(agg_q)).one()

    # Per-user breakdown
    per_user_q = (
        select(
            AIUsage.user_id,
            func.count(AIUsage.id).label("calls"),
            func.coalesce(func.sum(AIUsage.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsage.cost_usd), 0.0).label("cost_usd"),
        )
        .where(AIUsage.org_id == user.org_id, AIUsage.timestamp >= since)
        .group_by(AIUsage.user_id)
        .order_by(desc("cost_usd"))
    )
    per_user_rows = (await db.execute(per_user_q)).all()

    # Resolve usernames
    user_ids = [r.user_id for r in per_user_rows]
    user_map = {}
    if user_ids:
        u_rows = (await db.execute(select(User.id, User.username, User.name).where(User.id.in_(user_ids)))).all()
        user_map = {u.id: {"username": u.username, "name": u.name} for u in u_rows}

    per_user = [
        {
            "user_id": str(r.user_id),
            "username": user_map.get(r.user_id, {}).get("username", "?"),
            "name": user_map.get(r.user_id, {}).get("name", "?"),
            "calls": r.calls,
            "total_tokens": int(r.total_tokens),
            "cost_usd": float(r.cost_usd),
        }
        for r in per_user_rows
    ]

    # Recent calls
    recent_q = (
        select(AIUsage, User.username)
        .join(User, User.id == AIUsage.user_id)
        .where(AIUsage.org_id == user.org_id, AIUsage.timestamp >= since)
        .order_by(desc(AIUsage.timestamp))
        .limit(limit)
    )
    recent_rows = (await db.execute(recent_q)).all()
    recent = [
        {
            "id": str(row.AIUsage.id),
            "timestamp": row.AIUsage.timestamp.isoformat(),
            "username": row.username,
            "model": row.AIUsage.model,
            "operation": row.AIUsage.operation,
            "prompt_tokens": row.AIUsage.prompt_tokens,
            "output_tokens": row.AIUsage.output_tokens,
            "total_tokens": row.AIUsage.total_tokens,
            "latency_ms": row.AIUsage.latency_ms,
            "cost_usd": row.AIUsage.cost_usd,
        }
        for row in recent_rows
    ]

    return {
        "period_days": days,
        "aggregate": {
            "calls": agg_row.calls or 0,
            "prompt_tokens": int(agg_row.prompt_tokens or 0),
            "output_tokens": int(agg_row.output_tokens or 0),
            "total_tokens": int(agg_row.total_tokens or 0),
            "cost_usd": float(agg_row.cost_usd or 0.0),
            "avg_latency_ms": int(agg_row.avg_latency_ms or 0),
        },
        "by_user": per_user,
        "recent": recent,
    }
