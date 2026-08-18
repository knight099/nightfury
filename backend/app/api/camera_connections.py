"""Camera adjacency (the Map) and event journeys.

Adjacency is drawn by an operator, never inferred. Journeys correlate events
across those edges by timing — a plausibility signal, not an identity claim.
See ``services/journeys.py`` for why that distinction is load-bearing.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role, scope_to_sites
from app.models.camera import Camera
from app.models.camera_connection import CameraConnection
from app.models.event import Event
from app.models.site import Site
from app.models.user import User
from app.schemas.journey import (
    CameraConnectionResponse,
    CreateConnectionRequest,
    JourneyResponse,
    JourneyStepResponse,
    UpdateConnectionRequest,
)
from app.services.journeys import build_journey, connections_for_site, normalise_pair

router = APIRouter(prefix="/api", tags=["journeys"])


async def _load_site(site_id: uuid.UUID, user: User, db: AsyncSession) -> Site:
    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)
    q = scope_to_sites(q, Site.id, user)
    site = (await db.execute(q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get(
    "/sites/{site_id}/camera-connections",
    response_model=list[CameraConnectionResponse],
)
async def list_connections(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    site = await _load_site(site_id, user, db)
    rows = await connections_for_site(db, site.id)
    return [CameraConnectionResponse.model_validate(r) for r in rows]


@router.post(
    "/sites/{site_id}/camera-connections",
    response_model=CameraConnectionResponse,
    status_code=201,
)
async def create_connection(
    site_id: uuid.UUID,
    body: CreateConnectionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    site = await _load_site(site_id, user, db)

    if body.camera_a_id == body.camera_b_id:
        raise HTTPException(status_code=400, detail="A camera cannot connect to itself")

    cameras = (
        (
            await db.execute(
                select(Camera).where(
                    Camera.id.in_([body.camera_a_id, body.camera_b_id]),
                    Camera.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(cameras) != 2:
        raise HTTPException(status_code=404, detail="Camera not found")
    # Adjacency across sites is physically meaningless — two buildings are not
    # joined by a hallway — so this is rejected rather than quietly stored.
    if any(c.site_id != site.id for c in cameras):
        raise HTTPException(
            status_code=400, detail="Both cameras must belong to this site"
        )

    a_id, b_id = normalise_pair(body.camera_a_id, body.camera_b_id)
    existing = (
        await db.execute(
            select(CameraConnection).where(
                CameraConnection.camera_a_id == a_id,
                CameraConnection.camera_b_id == b_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Idempotent: drawing an edge that already exists returns it rather
        # than erroring, matching how the map UI behaves when two people draw
        # the same link.
        return CameraConnectionResponse.model_validate(existing)

    conn = CameraConnection(
        org_id=site.org_id,
        site_id=site.id,
        camera_a_id=a_id,
        camera_b_id=b_id,
        label=body.label,
    )
    db.add(conn)
    await db.flush()
    return CameraConnectionResponse.model_validate(conn)


@router.patch(
    "/sites/{site_id}/camera-connections/{connection_id}",
    response_model=CameraConnectionResponse,
)
async def update_connection(
    site_id: uuid.UUID,
    connection_id: uuid.UUID,
    body: UpdateConnectionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    site = await _load_site(site_id, user, db)
    conn = (
        await db.execute(
            select(CameraConnection).where(
                CameraConnection.id == connection_id, CameraConnection.site_id == site.id
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.label = body.label
    await db.flush()
    return CameraConnectionResponse.model_validate(conn)


@router.delete(
    "/sites/{site_id}/camera-connections/{connection_id}", status_code=204
)
async def delete_connection(
    site_id: uuid.UUID,
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    site = await _load_site(site_id, user, db)
    conn = (
        await db.execute(
            select(CameraConnection).where(
                CameraConnection.id == connection_id, CameraConnection.site_id == site.id
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    await db.delete(conn)
    await db.flush()


@router.get("/events/{event_id}/journey", response_model=JourneyResponse)
async def event_journey(
    event_id: uuid.UUID,
    window_minutes: int = Query(10, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Correlate this event forward across adjacent cameras.

    Most events return ``has_journey: false`` — that is the normal outcome,
    not an error. A journey only exists when something actually happened on a
    connected camera shortly afterwards.
    """
    from datetime import timedelta

    q = select(Event).where(Event.id == event_id)
    if user.role != "super_admin":
        q = q.where(Event.org_id == user.org_id)
    q = scope_to_sites(q, Event.site_id, user)
    event = (await db.execute(q)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    journey = await build_journey(db, event, window=timedelta(minutes=window_minutes))
    return JourneyResponse(
        seed_event_id=journey.seed_event_id,
        has_journey=journey.has_journey,
        summary=journey.summary,
        steps=[JourneyStepResponse(**vars(s)) for s in journey.steps],
    )
