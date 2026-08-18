import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, permitted_site_ids
from app.core.redis import get_redis
from app.models.digest import Digest
from app.models.digest_preferences import DigestPreferences
from app.models.user import User
from app.schemas.digest import (
    DigestListResponse,
    DigestPreferencesResponse,
    DigestPreferencesUpdate,
    DigestRequest,
    DigestResponse,
)
from app.services.digest.deps import get_digest_service
from app.services.digest.service import DigestService

router = APIRouter(prefix="/api/digests", tags=["digests"])


def _scope(query, current: User):
    if current.role == "super_admin":
        return query
    query = query.where(Digest.org_id == current.org_id)

    site_ids = permitted_site_ids(current)
    if site_ids is None:
        return query
    # A site-restricted account sees only digests generated FOR one of its
    # sites. Org-wide digests (site_id NULL — the scheduled morning/evening
    # runs) are deliberately excluded rather than shown: they summarise every
    # event in the organisation, so showing one would leak exactly what the
    # site restriction exists to prevent.
    return query.where(Digest.site_id.in_(site_ids))


async def _redis_dep():
    return await get_redis()


async def _enforce_user_rate_limit(redis, user_id):
    key = f"digest:ondemand:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)
    if count > settings.digest_on_demand_per_user_hourly_limit:
        raise HTTPException(429, "On-demand digest hourly limit reached. Try again later.")


async def _get_or_create_prefs(db: AsyncSession, org_id) -> DigestPreferences:
    row = (
        await db.execute(
            select(DigestPreferences).where(DigestPreferences.org_id == org_id)
        )
    ).scalar_one_or_none()
    if row:
        return row
    row = DigestPreferences(org_id=org_id)
    db.add(row)
    # Use flush (not commit) — caller controls the transaction.
    await db.flush()
    await db.refresh(row)
    return row


@router.get("/preferences", response_model=DigestPreferencesResponse)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.org_id is None:
        raise HTTPException(400, "super_admin has no preferences")
    prefs = await _get_or_create_prefs(db, current.org_id)
    return DigestPreferencesResponse.model_validate(prefs)


@router.put("/preferences", response_model=DigestPreferencesResponse)
async def update_preferences(
    body: DigestPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.org_id is None:
        raise HTTPException(400, "super_admin has no preferences")
    prefs = await _get_or_create_prefs(db, current.org_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    await db.flush()
    await db.refresh(prefs)
    return DigestPreferencesResponse.model_validate(prefs)


@router.get("", response_model=DigestListResponse)
async def list_digests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    base = select(Digest).order_by(Digest.created_at.desc())
    rows = (
        await db.execute(_scope(base, current).limit(limit).offset(offset))
    ).scalars().all()
    total = (
        await db.execute(_scope(select(func.count(Digest.id)), current))
    ).scalar_one()
    return DigestListResponse(
        items=[DigestResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{digest_id}", response_model=DigestResponse)
async def get_digest(
    digest_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = (
        await db.execute(_scope(select(Digest).where(Digest.id == digest_id), current))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Digest not found")
    return DigestResponse.model_validate(row)


@router.post("", response_model=DigestResponse, status_code=201)
async def create_on_demand(
    body: DigestRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(_redis_dep),
    current: User = Depends(get_current_user),
    service: DigestService = Depends(get_digest_service),
):
    if body.end - body.start > timedelta(days=settings.digest_max_range_days):
        raise HTTPException(400, f"Range cannot exceed {settings.digest_max_range_days} days")
    if current.org_id is None:
        raise HTTPException(400, "super_admin cannot run on-demand digests")
    # Generation does not pass through _scope, so the restriction is applied
    # here too — otherwise a site-scoped user could not *read* an org-wide
    # digest but could still *create* one and then read it.
    site_ids = permitted_site_ids(current)
    if site_ids is not None:
        if body.site_id is None:
            raise HTTPException(
                status_code=400,
                detail="site_id is required — your account is restricted to specific sites",
            )
        if body.site_id not in site_ids:
            raise HTTPException(
                status_code=403, detail="You do not have access to that site"
            )

    await _enforce_user_rate_limit(redis, current.id)
    digest = await service.generate(
        org_id=current.org_id,
        kind="on_demand",
        start=body.start,
        end=body.end,
        camera_ids=body.camera_ids,
        site_id=body.site_id,
        requested_by=current.id,
    )
    return DigestResponse.model_validate(digest)
