import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.camera import Camera
from app.models.site import Site
from app.models.user import User
from app.schemas.site import CreateSiteRequest, SiteResponse, UpdateSiteRequest
from app.services.soft_delete_service import soft_delete_service

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=list[SiteResponse])
async def list_sites(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = Query(None),
):
    q = select(Site).where(Site.deleted_at.is_(None))
    if user.role == "super_admin":
        if org_id:
            q = q.where(Site.org_id == org_id)
    else:
        q = q.where(Site.org_id == user.org_id)

    result = await db.execute(q.order_by(Site.created_at.desc()))
    return [SiteResponse.model_validate(s) for s in result.scalars().all()]


@router.post("", response_model=SiteResponse, status_code=201)
async def create_site(
    body: CreateSiteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = Query(None),
):
    require_role(user, "admin")

    target_org_id = user.org_id
    if user.role == "super_admin" and org_id:
        target_org_id = org_id
    elif user.role == "super_admin" and not org_id:
        raise HTTPException(status_code=400, detail="Super admin must specify org_id")

    site = Site(org_id=target_org_id, name=body.name, address=body.address, timezone=body.timezone)
    db.add(site)
    await db.flush()
    return SiteResponse.model_validate(site)


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: uuid.UUID,
    body: UpdateSiteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)

    result = await db.execute(q)
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    await db.flush()
    return SiteResponse.model_validate(site)


@router.delete("/{site_id}", status_code=204)
async def delete_site(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)

    result = await db.execute(q)
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    camera_count = (
        await db.execute(
            select(func.count())
            .select_from(Camera)
            .where(Camera.site_id == site_id, Camera.deleted_at.is_(None))
        )
    ).scalar_one()
    if camera_count:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a site that still has cameras",
        )
    await soft_delete_service.delete_site(site, db)


@router.post("/{site_id}/restore", response_model=SiteResponse)
async def restore_site(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = select(Site).where(Site.id == site_id)
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)

    result = await db.execute(q)
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if site.deleted_at is None:
        raise HTTPException(status_code=400, detail="Site is not deleted")
    await soft_delete_service.restore_site(site, db)
    return SiteResponse.model_validate(site)
