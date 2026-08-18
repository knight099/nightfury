"""Fleet view: appliances at a site, their capacity, and coverage.

Read endpoints plus one write (pinning a camera to a specific appliance).
All placement logic lives in ``services/camera_placement.py`` — these handlers
load, delegate, and shape the response.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role, scope_to_sites
from app.models.agent import Agent
from app.models.camera import Camera
from app.models.footfall_count import FootfallCount
from app.models.site import Site
from app.models.user import User
from app.schemas.fleet import FleetAgent, FleetCamera, FleetResponse, PinCameraRequest
from app.services.camera_placement import DEFAULT_CAPACITY, reconcile_site

router = APIRouter(prefix="/api/fleet", tags=["fleet"])

# An agent that has not beaten in this long is treated as not working, and its
# capacity stops counting toward the site's coverage. Three missed 30s beats —
# long enough to ride out a restart, short enough that a dead box shows up
# before the next shift.
STALE_AFTER = timedelta(seconds=100)


async def _load_site(site_id: uuid.UUID, user: User, db: AsyncSession) -> Site:
    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)
    q = scope_to_sites(q, Site.id, user)
    site = (await db.execute(q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("/sites/{site_id}", response_model=FleetResponse)
async def get_site_fleet(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FleetResponse:
    site = await _load_site(site_id, user, db)

    agents = list(
        (
            await db.execute(
                select(Agent)
                .where(Agent.org_id == site.org_id, Agent.site_id == site.id)
                .order_by(Agent.created_at)
            )
        )
        .scalars()
        .all()
    )
    cameras = list(
        (
            await db.execute(
                select(Camera)
                .where(Camera.site_id == site.id, Camera.deleted_at.is_(None))
                .order_by(Camera.name)
            )
        )
        .scalars()
        .all()
    )

    by_agent: dict[uuid.UUID, list[Camera]] = {a.id: [] for a in agents}
    unassigned: list[Camera] = []
    for camera in cameras:
        if camera.agent_id in by_agent:
            by_agent[camera.agent_id].append(camera)
        else:
            # Covers both agent_id NULL and — defensively — a camera pointing
            # at an agent that is no longer at this site.
            unassigned.append(camera)

    now = datetime.now(timezone.utc)
    fleet_agents: list[FleetAgent] = []
    capacity_total = 0
    cameras_covered = 0

    for agent in agents:
        capacity = (
            agent.capacity_cameras if agent.capacity_cameras is not None else DEFAULT_CAPACITY
        )
        is_stale = agent.last_seen_at is None or (now - agent.last_seen_at) > STALE_AFTER
        agent_cameras = by_agent[agent.id]

        # A stale box contributes neither capacity nor coverage — counting it
        # would report a site as covered while nothing is being analysed.
        if not is_stale:
            capacity_total += capacity
            cameras_covered += len(agent_cameras)

        fleet_agents.append(
            FleetAgent(
                id=agent.id,
                machine_id=agent.machine_id,
                status=agent.status,
                version=agent.version,
                last_seen_at=agent.last_seen_at,
                capacity_cameras=agent.capacity_cameras,
                capacity_source=agent.capacity_source,
                assigned_count=agent.assigned_count,
                assignment_version=agent.assignment_version,
                load_state=agent.load_state,
                load_reason=agent.load_reason,
                is_stale=is_stale,
                spare_capacity=max(0, capacity - len(agent_cameras)),
                cameras=[FleetCamera.model_validate(c) for c in agent_cameras],
            )
        )

    return FleetResponse(
        site_id=site.id,
        site_name=site.name,
        agents=fleet_agents,
        unassigned_cameras=[FleetCamera.model_validate(c) for c in unassigned],
        cameras_total=len(cameras),
        cameras_covered=cameras_covered,
        capacity_total=capacity_total,
        capacity_spare=max(0, capacity_total - cameras_covered),
    )


@router.post("/cameras/{camera_id}/pin", response_model=FleetResponse)
async def pin_camera(
    camera_id: uuid.UUID,
    body: PinCameraRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FleetResponse:
    """Pin a camera to a specific appliance, or clear the pin.

    An operator always knows something about the building that the packer does
    not. A pin is honoured absolutely and never moved by reconciliation.
    """
    require_role(user, "admin")

    q = select(Camera).where(Camera.id == camera_id, Camera.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Camera.org_id == user.org_id)
    q = scope_to_sites(q, Camera.site_id, user)
    camera = (await db.execute(q)).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    if body.agent_id is not None:
        agent = (
            await db.execute(
                select(Agent).where(
                    Agent.id == body.agent_id, Agent.org_id == camera.org_id
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found in this org")
        # Rejected here rather than silently unassigned at placement time: an
        # agent on another LAN physically cannot reach this camera, and the
        # operator should be told now, not discover a dead camera later.
        if agent.site_id != camera.site_id:
            raise HTTPException(
                status_code=400,
                detail="Agent is at a different site and cannot reach this camera",
            )

    camera.pinned_agent_id = body.agent_id
    await db.flush()
    await reconcile_site(db, camera.org_id, camera.site_id)

    return await get_site_fleet(camera.site_id, db=db, user=user)


# ─── Footfall ───────────────────────────────────────────────────────────────


@router.get("/sites/{site_id}/footfall")
async def site_footfall(
    site_id: uuid.UUID,
    hours: int = 24,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Hourly footfall estimate for a site.

    Buckets are summed at read time rather than stored as running totals, so
    the same rows can be re-aggregated at any granularity later.

    `estimate: true` and the accompanying caveat are part of the response on
    purpose. These counts come from tracking without re-identification — they
    over-count on occlusion and under-count in crowds — so any client that
    renders them as an exact visitor total is misrepresenting them, and the
    payload says so rather than relying on the client to remember.
    """
    site = await _load_site(site_id, user, db)
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 31)))

    rows = (
        await db.execute(
            select(
                func.date_trunc("hour", FootfallCount.bucket_at).label("hour"),
                FootfallCount.line_name,
                func.sum(FootfallCount.count_in).label("in_"),
                func.sum(FootfallCount.count_out).label("out_"),
            )
            .where(FootfallCount.site_id == site.id, FootfallCount.bucket_at >= since)
            .group_by("hour", FootfallCount.line_name)
            .order_by("hour")
        )
    ).all()

    return {
        "site_id": str(site.id),
        "site_name": site.name,
        "estimate": True,
        "caveat": (
            "Estimated from camera detections, not a turnstile count. Reliable "
            "as a relative trend; not exact totals."
        ),
        "buckets": [
            {
                "hour": r.hour.isoformat(),
                "line_name": r.line_name,
                "in": int(r.in_ or 0),
                "out": int(r.out_ or 0),
            }
            for r in rows
        ],
    }
