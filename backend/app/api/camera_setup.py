"""Operator-facing endpoints for agentic camera setup.

Approval is the only path that writes camera configuration. A proposal on its
own changes nothing.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agents import enqueue_setup_job
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role, scope_to_sites
from app.models.camera import Camera
from app.models.camera_setup import CameraSetupProposal, SetupRun
from app.models.site import Site
from app.models.user import User
from app.schemas.camera_setup import (
    ApproveGroupRequest,
    ProposalResponse,
    ReviewGroupResponse,
    SetupJob,
    SetupRunResponse,
    SetupRunSummary,
    StartRunRequest,
)
from app.services.camera_setup.grouping import group_proposals

router = APIRouter(prefix="/api", tags=["camera-setup"])

# Cap the run history returned per site — this is a "resume where I left
# off" list for one operator, not an audit log.
MAX_RUNS_LISTED = 20


async def _load_site(site_id: uuid.UUID, user: User, db: AsyncSession) -> Site:
    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)
    q = scope_to_sites(q, Site.id, user)
    site = (await db.execute(q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _load_run(run_id: uuid.UUID, user: User, db: AsyncSession) -> SetupRun:
    q = select(SetupRun).where(SetupRun.id == run_id)
    if user.role != "super_admin":
        q = q.where(SetupRun.org_id == user.org_id)
    q = scope_to_sites(q, SetupRun.site_id, user)
    run = (await db.execute(q)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Setup run not found")
    return run


@router.post("/sites/{site_id}/setup-runs", response_model=SetupRunResponse, status_code=201)
async def start_setup_run(
    site_id: uuid.UUID,
    body: StartRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a setup run over an operator-selected batch of cameras."""
    require_role(user, "admin")
    site = await _load_site(site_id, user, db)

    cameras = list(
        (
            await db.execute(
                select(Camera).where(
                    Camera.id.in_(body.camera_ids),
                    Camera.site_id == site.id,
                    Camera.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not cameras:
        raise HTTPException(status_code=404, detail="No cameras found at this site")

    requested_ids = set(body.camera_ids)
    found_ids = {c.id for c in cameras}
    missing = requested_ids - found_ids
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(missing)} of {len(requested_ids)} requested cameras were not "
                "found at this site"
            ),
        )

    unplaced = [c.name for c in cameras if c.agent_id is None]
    if unplaced:
        # Without an agent there is nothing to observe the camera. Say so
        # rather than creating proposals that can never be fulfilled.
        raise HTTPException(
            status_code=400,
            detail=f"These cameras are not assigned to an appliance yet: {', '.join(unplaced)}",
        )

    run = SetupRun(
        org_id=site.org_id,
        site_id=site.id,
        requested_by=user.id,
        status="running",
        camera_count=len(cameras),
    )
    db.add(run)
    await db.flush()

    for camera in cameras:
        db.add(
            CameraSetupProposal(
                org_id=site.org_id,
                site_id=site.id,
                camera_id=camera.id,
                run_id=run.id,
                status="pending",
            )
        )
        await enqueue_setup_job(
            camera.agent_id,
            SetupJob(
                camera_id=camera.id,
                camera_name=camera.name,
                rtsp_url=camera.rtsp_url,
            ),
        )
    await db.flush()
    return await _run_response(run, db)


@router.get("/sites/{site_id}/setup-runs", response_model=list[SetupRunSummary])
async def list_setup_runs(
    site_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List this site's setup runs, newest first, so a page refresh can find
    and resume one still in progress instead of orphaning it."""
    site = await _load_site(site_id, user, db)

    runs = list(
        (
            await db.execute(
                select(SetupRun)
                .where(SetupRun.site_id == site.id)
                .order_by(SetupRun.created_at.desc())
                .limit(MAX_RUNS_LISTED)
            )
        )
        .scalars()
        .all()
    )
    if not runs:
        return []

    run_ids = [r.id for r in runs]
    proposals = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id.in_(run_ids))
            )
        )
        .scalars()
        .all()
    )
    pending_by_run: dict[uuid.UUID, int] = {}
    for p in proposals:
        if p.status == "pending":
            pending_by_run[p.run_id] = pending_by_run.get(p.run_id, 0) + 1

    return [
        SetupRunSummary(
            id=r.id,
            site_id=r.site_id,
            status=r.status,
            camera_count=r.camera_count,
            pending=pending_by_run.get(r.id, 0),
            created_at=r.created_at,
        )
        for r in runs
    ]


async def _run_response(run: SetupRun, db: AsyncSession) -> SetupRunResponse:
    rows = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    groups = [
        ReviewGroupResponse(
            scene_type=g.scene_type,
            label=g.label,
            bulk_approvable=g.bulk_approvable,
            shared_config=g.shared_config,
            proposals=[ProposalResponse.model_validate(by_id[i]) for i in g.proposal_ids],
            differing=[ProposalResponse.model_validate(by_id[i]) for i in g.differing_proposal_ids],
        )
        for g in group_proposals(rows)
    ]
    return SetupRunResponse(
        id=run.id,
        site_id=run.site_id,
        status=run.status,
        camera_count=run.camera_count,
        pending=sum(1 for r in rows if r.status == "pending"),
        groups=groups,
    )


@router.get("/setup-runs/{run_id}", response_model=SetupRunResponse)
async def get_setup_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await _load_run(run_id, user, db)
    return await _run_response(run, db)


def _apply(camera: Camera, proposal: dict) -> None:
    """Write an approved proposal onto the camera.

    Only ever called from an approve endpoint, and only for a proposal whose
    status is `proposed` — never `needs_input` or `failed`.
    """
    camera.enabled_events = list(proposal.get("enabled_events") or [])
    camera.sensitivity = proposal.get("sensitivity") or "medium"
    # The agent-facing contract (prompt + validator) proposes zones shaped
    # {"name", "polygon"}. The platform's canonical zone shape is
    # {"name", "points"} — read by the pipeline's zone tagging
    # (agent/pipeline/camera_worker.py::_zone_for_bbox, which does
    # zone.get("points", [])) and by the frontend zone editor
    # (frontend/src/components/cameras/ZonesEditor.tsx, which reads z.points).
    # Translate here, at the point config is written, rather than renaming the
    # key anywhere upstream — the agent's contract stays `polygon`.
    camera.detection_zones = [
        {**{k: v for k, v in z.items() if k not in ("name", "polygon")},
         "name": z.get("name"), "points": z.get("polygon") or []}
        for z in (proposal.get("zones") or [])
        if isinstance(z, dict)
    ]
    camera.counting_lines = list(proposal.get("counting_lines") or [])


async def _maybe_complete_run(run_id: uuid.UUID, db: AsyncSession) -> None:
    """Mark a run complete once every one of its proposals is terminal.

    Shared by both approve endpoints so the run's status reflects reality
    whether cameras are approved one at a time or as a bulk group.
    """
    rows = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    if rows and all(r.status in ("approved", "rejected") for r in rows):
        run = (
            await db.execute(select(SetupRun).where(SetupRun.id == run_id))
        ).scalar_one_or_none()
        if run is not None:
            run.status = "complete"


@router.post("/setup-proposals/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve one camera's proposal and write its configuration."""
    require_role(user, "admin")

    q = select(CameraSetupProposal).where(CameraSetupProposal.id == proposal_id)
    if user.role != "super_admin":
        q = q.where(CameraSetupProposal.org_id == user.org_id)
    q = scope_to_sites(q, CameraSetupProposal.site_id, user)
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if row.status != "proposed":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve a proposal in state '{row.status}'",
        )

    camera = (
        await db.execute(
            select(Camera).where(
                Camera.id == row.camera_id,
                Camera.org_id == row.org_id,
                Camera.site_id == row.site_id,
                Camera.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    _apply(camera, row.proposal)
    row.status = "approved"
    row.approved_by = user.id
    row.approved_at = datetime.now(timezone.utc)
    await _maybe_complete_run(row.run_id, db)
    await db.flush()
    return ProposalResponse.model_validate(row)


@router.post("/setup-runs/{run_id}/approve-group", response_model=SetupRunResponse)
async def approve_group(
    run_id: uuid.UUID,
    body: ApproveGroupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve every agreeing proposal in one scene group.

    Detection configuration only. Alert rules are confirmed per camera, and
    a non-bulk-approvable group (needs_input, or a group of one) is refused.
    """
    require_role(user, "admin")
    run = await _load_run(run_id, user, db)

    rows = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    target = next((g for g in group_proposals(rows) if g.scene_type == body.scene_type), None)
    if target is None:
        raise HTTPException(status_code=404, detail="No such group in this run")
    if not target.bulk_approvable:
        raise HTTPException(
            status_code=400, detail="This group must be reviewed one camera at a time"
        )

    by_id = {r.id: r for r in rows}
    camera_ids = [by_id[i].camera_id for i in target.proposal_ids]
    cameras = {
        c.id: c
        for c in (
            await db.execute(
                select(Camera).where(
                    Camera.id.in_(camera_ids),
                    Camera.org_id == run.org_id,
                    Camera.site_id == run.site_id,
                    Camera.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    }

    now = datetime.now(timezone.utc)
    for pid in target.proposal_ids:
        row = by_id[pid]
        if row.status != "proposed":
            continue
        camera = cameras.get(row.camera_id)
        if camera is None:
            continue
        _apply(camera, row.proposal)
        row.status = "approved"
        row.approved_by = user.id
        row.approved_at = now

    await _maybe_complete_run(run.id, db)
    await db.flush()
    return await _run_response(run, db)
