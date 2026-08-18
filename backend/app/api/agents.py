"""Agent onboarding API.

Endpoints:
- POST /api/agents/pair-codes              (auth)   -> mint a 6-digit pair code (super_admin must pass org_id)
- POST /api/agents/pair                    (public) -> redeem a pair code for a device token
- GET  /api/agents                         (auth)   -> list paired agents in caller's org
- GET  /api/agents/{agent_id}              (auth)   -> agent detail incl. cameras_streaming
- POST /api/agents/me/discovered           (agent)  -> agent pushes LAN ONVIF discovery results
- POST /api/agents/{agent_id}/discover     (auth)   -> read the agent's latest discovery results
- POST /api/agents/{agent_id}/cameras      (auth)   -> register a camera bound to the agent
- GET  /api/agents/me/resolve-jobs         (agent)  -> drain pending ONVIF GetStreamUri jobs
- POST /api/agents/me/resolve-jobs/{id}    (agent)  -> agent reports resolved RTSP URL
- GET  /api/agents/me/setup-jobs           (agent)  -> drain pending camera-setup jobs
- POST /api/agents/me/setup-jobs/{id}      (agent)  -> pipeline reports a setup proposal
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_agent_from_token, get_current_user, scope_to_sites
from app.core.redis import get_redis
from app.models.agent import Agent
from app.models.camera import Camera
from app.models.camera_setup import CameraSetupProposal
from app.models.organization import Organization
from app.models.site import Site
from app.models.user import User
from app.schemas.agent import (
    AgentDetailResponse,
    AgentListResponse,
    AgentSummary,
    DiscoveredDevice,
    DiscoverPushRequest,
    DiscoverResponse,
    PairCodeRequest,
    PairCodeResponse,
    PairRequest,
    PairResponse,
    RegisterCameraRequest,
    RegisterCameraResponse,
    ResolveJob,
    ResolveJobsResponse,
    ResolveResultRequest,
)
from app.schemas.camera_setup import SetupJob, SetupJobsResponse, SetupResultRequest
from app.services.camera_setup.validator import validate_proposal
from app.services.device_token_service import DeviceTokenService
from app.services.pairing_service import PairingService

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post(
    "/pair-codes",
    response_model=PairCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pair_code(
    payload: PairCodeRequest = PairCodeRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PairCodeResponse:
    if user.role == "super_admin":
        # super_admin has no org of their own; they must pass org_id in the body
        if payload.org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="super_admin must pass org_id in the request body",
            )
        org = (
            await db.execute(
                select(Organization).where(
                    Organization.id == payload.org_id, Organization.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="org not found")
        org_id = org.id
    elif user.org_id is not None:
        org_id = user.org_id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user has no org assigned",
        )

    if user.role != "super_admin":
        r = await get_redis()
        rate_key = f"paircode:rate:{user.id}"
        count = await r.incr(rate_key)
        if count == 1:
            await r.expire(rate_key, 3600)
        if count > 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many pairing codes — try again in an hour",
            )

    service = PairingService(db)
    code = await service.mint_code(org_id, user.id)
    row = await service.get_code(code)
    assert row is not None
    return PairCodeResponse(code=row.code, expires_at=row.expires_at)


@router.post("/pair", response_model=PairResponse)
async def pair_agent(
    payload: PairRequest,
    db: AsyncSession = Depends(get_db),
) -> PairResponse:
    service = PairingService(db)
    try:
        org_id = await service.redeem_code(payload.code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    token, token_hash, token_id = DeviceTokenService.mint()
    agent = Agent(
        org_id=org_id,
        machine_id=payload.machine_id,
        pubkey=payload.pubkey,
        device_token_hash=token_hash,
        device_token_id=token_id,
        version=payload.version,
        status="online",
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(agent)
    await db.flush()

    return PairResponse(
        device_token=token,
        relay_url=settings.relay_public_url,
        org_id=org_id,
        agent_id=agent.id,
    )


@router.get("", response_model=AgentListResponse)
async def list_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentListResponse:
    stmt = scope_to_sites(
        select(Agent).order_by(Agent.created_at.desc()), Agent.site_id, user
    )
    if user.role != "super_admin":
        stmt = stmt.where(Agent.org_id == user.org_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return AgentListResponse(
        agents=[AgentSummary.model_validate(r) for r in rows]
    )


async def _load_agent_for_user(
    agent_id: uuid.UUID, user: User, db: AsyncSession
) -> Agent:
    stmt = select(Agent).where(Agent.id == agent_id)
    if user.role != "super_admin":
        stmt = stmt.where(Agent.org_id == user.org_id)
    # Agents carry a site_id, so an appliance in a building the caller has no
    # access to is out of scope the same way its cameras are.
    stmt = scope_to_sites(stmt, Agent.site_id, user)
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


@router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentDetailResponse:
    agent = await _load_agent_for_user(agent_id, user, db)
    streaming = (
        await db.execute(
            select(func.count())
            .select_from(Camera)
            .where(Camera.agent_id == agent.id, Camera.status == "online")
        )
    ).scalar_one()
    return AgentDetailResponse(
        id=agent.id,
        org_id=agent.org_id,
        machine_id=agent.machine_id,
        version=agent.version,
        transport=agent.transport,
        status=agent.status,
        last_seen_at=agent.last_seen_at,
        created_at=agent.created_at,
        cameras_streaming=int(streaming or 0),
    )


DISCOVERY_TTL_SECONDS = 600


def _discovery_key(agent_id: uuid.UUID) -> str:
    return f"agent:discovered:{agent_id}"


@router.post("/me/discovered", status_code=status.HTTP_204_NO_CONTENT)
async def push_discovered(
    payload: DiscoverPushRequest,
    agent: Agent = Depends(get_agent_from_token),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Agent-authenticated push of LAN ONVIF discovery results.

    The backend cannot reach the user's LAN, so the agent periodically scans
    (WS-Discovery multicast) and uploads what it found. Results are kept in
    Redis with a short TTL — they are a live view, not durable state.
    """
    r = await get_redis()
    devices = [d.model_dump() for d in payload.devices]
    await r.set(
        _discovery_key(agent.id), json.dumps(devices), ex=DISCOVERY_TTL_SECONDS
    )
    agent.last_seen_at = datetime.now(timezone.utc)
    agent.status = "online"
    await db.flush()


@router.post("/{agent_id}/discover", response_model=DiscoverResponse)
async def discover_cameras(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """Return the agent's most recent LAN discovery results.

    Served from the Redis snapshot pushed by the agent (see
    ``POST /api/agents/me/discovered``). Empty list means nothing found yet —
    the wizard then falls back to manual brand-template entry.
    """
    await _load_agent_for_user(agent_id, user, db)
    r = await get_redis()
    raw = await r.get(_discovery_key(agent_id))
    if not raw:
        return DiscoverResponse(devices=[])
    return DiscoverResponse(
        devices=[DiscoveredDevice(**d) for d in json.loads(raw)]
    )


RESOLVE_QUEUE_TTL_SECONDS = 600


def _resolve_queue_key(agent_id: uuid.UUID) -> str:
    return f"agent:resolve_jobs:{agent_id}"


async def _enqueue_resolve_job(agent_id: uuid.UUID, job: ResolveJob) -> None:
    r = await get_redis()
    key = _resolve_queue_key(agent_id)
    await r.rpush(key, job.model_dump_json(by_alias=True))
    await r.expire(key, RESOLVE_QUEUE_TTL_SECONDS)


SETUP_QUEUE_TTL_SECONDS = 3600


def _setup_queue_key(agent_id: uuid.UUID) -> str:
    return f"agent:{agent_id}:setup-jobs"


async def enqueue_setup_job(agent_id: uuid.UUID, job: SetupJob) -> None:
    r = await get_redis()
    key = _setup_queue_key(agent_id)
    await r.rpush(key, job.model_dump_json())
    await r.expire(key, SETUP_QUEUE_TTL_SECONDS)


async def _default_site(org_id: uuid.UUID, db: AsyncSession) -> Site:
    stmt = (
        select(Site)
        .where(Site.org_id == org_id, Site.deleted_at.is_(None))
        .order_by(Site.created_at)
        .limit(1)
    )
    site = (await db.execute(stmt)).scalar_one_or_none()
    if site is None:
        site = Site(org_id=org_id, name="Home")
        db.add(site)
        await db.flush()
    return site


@router.post(
    "/{agent_id}/cameras",
    response_model=RegisterCameraResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_camera(
    agent_id: uuid.UUID,
    payload: RegisterCameraRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegisterCameraResponse:
    agent = await _load_agent_for_user(agent_id, user, db)

    if payload.site_id is not None:
        site_stmt = select(Site).where(
            Site.id == payload.site_id, Site.org_id == agent.org_id, Site.deleted_at.is_(None)
        )
        site = (await db.execute(site_stmt)).scalar_one_or_none()
        if site is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="site not found in agent's org",
            )
    else:
        site = await _default_site(agent.org_id, db)

    if payload.rtsp_url:
        rtsp_url = payload.rtsp_url
        camera_status = "offline"
    elif payload.onvif_xaddr:
        rtsp_url = None
        camera_status = "pending"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="either rtsp_url or onvif_xaddr is required",
        )

    camera = Camera(
        org_id=agent.org_id,
        site_id=site.id,
        agent_id=agent.id,
        name=payload.name,
        ingest_mode="rtsp_pull",
        rtsp_url=rtsp_url,
        enabled_events=["person", "vehicle", "intrusion"],
        detection_zones=[],
        sensitivity="medium",
        status=camera_status,
    )
    db.add(camera)
    await db.flush()

    if payload.onvif_xaddr:
        await _enqueue_resolve_job(
            agent.id,
            ResolveJob(
                camera_id=camera.id,
                xaddr=payload.onvif_xaddr,
                user=payload.user,
                password=payload.password,
            ),
        )

    return RegisterCameraResponse(camera_id=camera.id, status=camera_status)


@router.get("/me/resolve-jobs", response_model=ResolveJobsResponse)
async def get_resolve_jobs(
    agent: Agent = Depends(get_agent_from_token),
) -> ResolveJobsResponse:
    """Drain pending ONVIF GetStreamUri jobs for this agent.

    Jobs are popped (not peeked) — if the agent dies mid-job the camera
    stays in ``pending`` status and the user can retry from the UI.
    """
    r = await get_redis()
    key = _resolve_queue_key(agent.id)
    jobs: list[ResolveJob] = []
    while True:
        raw = await r.lpop(key)
        if raw is None:
            break
        jobs.append(ResolveJob.model_validate_json(raw))
    return ResolveJobsResponse(jobs=jobs)


@router.post("/me/resolve-jobs/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def post_resolve_result(
    camera_id: uuid.UUID,
    payload: ResolveResultRequest,
    agent: Agent = Depends(get_agent_from_token),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Agent reports the resolved RTSP URL (or an error) for a camera."""
    stmt = select(Camera).where(
        Camera.id == camera_id, Camera.agent_id == agent.id, Camera.deleted_at.is_(None)
    )
    camera = (await db.execute(stmt)).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="camera not found")

    if payload.rtsp_url:
        camera.rtsp_url = payload.rtsp_url
        camera.status = "offline"
    else:
        camera.status = "error"
    await db.flush()


@router.get("/me/setup-jobs", response_model=SetupJobsResponse)
async def get_setup_jobs(
    agent: Agent = Depends(get_agent_from_token),
) -> SetupJobsResponse:
    """Drain pending camera-setup jobs for this agent.

    Polled by the PYTHON PIPELINE, not the Go agent: the pipeline is the
    process that holds decoded frames and can call Gemini. It authenticates
    with the same device token.

    Jobs are popped. The camera_setup_proposals row — not this queue — is the
    source of truth, so a lost job leaves a visible `pending` proposal the
    operator can retry.
    """
    r = await get_redis()
    key = _setup_queue_key(agent.id)
    jobs: list[SetupJob] = []
    while True:
        raw = await r.lpop(key)
        if raw is None:
            break
        jobs.append(SetupJob.model_validate_json(raw))
    return SetupJobsResponse(jobs=jobs)


@router.post("/me/setup-jobs/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def post_setup_result(
    camera_id: uuid.UUID,
    payload: SetupResultRequest,
    agent: Agent = Depends(get_agent_from_token),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Record the pipeline's proposal for one camera.

    Never writes camera config — only the proposal row. Approval is a separate,
    human action.
    """
    stmt = (
        select(CameraSetupProposal)
        .join(Camera, Camera.id == CameraSetupProposal.camera_id)
        .where(
            CameraSetupProposal.camera_id == camera_id,
            CameraSetupProposal.status == "pending",
            Camera.agent_id == agent.id,
        )
        .order_by(CameraSetupProposal.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no pending proposal")

    if payload.error or not payload.proposal:
        row.status = "failed"
        row.error = payload.error or "no proposal returned"
        await db.flush()
        return

    reasons = validate_proposal(payload.proposal, payload.frame_width, payload.frame_height)
    row.proposal = payload.proposal
    # The raw model reply goes into the JSONB `proposal` column verbatim,
    # unchanged — that's the audit record. But the typed columns below are
    # bounded/typed (scene_type is String(32), confidence is Float), and the
    # Gemini call has no response schema, so a malformed reply (confidence as
    # a string, an oversized scene_type, ...) must not raise at flush. We
    # never coerce or repair a bad value into a valid one — that would be a
    # silent correction of a proposal the model never actually justified.
    # Instead we leave the column NULL and let `reasons`/`error` carry the
    # explanation, so a malformed proposal becomes `needs_input`, not a 500.
    scene_type = payload.proposal.get("scene_type")
    row.scene_type = scene_type if isinstance(scene_type, str) and len(scene_type) <= 32 else None

    scene_description = payload.proposal.get("scene_description")
    row.scene_description = scene_description if isinstance(scene_description, str) else None

    confidence = payload.proposal.get("confidence")
    row.confidence = (
        float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        else None
    )

    rationale = payload.proposal.get("rationale")
    row.rationale = rationale if isinstance(rationale, str) else None

    if reasons:
        # Never corrected — a corrected proposal is no longer the thing the
        # model justified in its rationale.
        row.status = "needs_input"
        row.error = "; ".join(reasons)
    else:
        row.status = "proposed"
        row.error = None
    await db.flush()
