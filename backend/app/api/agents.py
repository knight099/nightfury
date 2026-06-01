"""Agent onboarding API.

Endpoints:
- POST /api/agents/pair-codes              (auth)   -> mint a 6-digit pair code
- POST /api/agents/pair                    (public) -> redeem a pair code for a device token
- GET  /api/agents                         (auth)   -> list paired agents in caller's org
- GET  /api/agents/{agent_id}              (auth)   -> agent detail incl. cameras_streaming
- POST /api/agents/{agent_id}/discover     (auth)   -> trigger ONVIF discovery on the agent
- POST /api/agents/{agent_id}/cameras      (auth)   -> register a camera bound to the agent
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.models.agent import Agent
from app.models.camera import Camera
from app.models.site import Site
from app.models.user import User
from app.schemas.agent import (
    AgentDetailResponse,
    AgentListResponse,
    AgentSummary,
    DiscoverResponse,
    PairCodeResponse,
    PairRequest,
    PairResponse,
    RegisterCameraRequest,
    RegisterCameraResponse,
)
from app.services.device_token_service import DeviceTokenService
from app.services.pairing_service import PairingService

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post(
    "/pair-codes",
    response_model=PairCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pair_code(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PairCodeResponse:
    if user.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="super_admin must select an org first",
        )

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
    code = await service.mint_code(user.org_id, user.id)
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

    token, token_hash = DeviceTokenService.mint()
    agent = Agent(
        org_id=org_id,
        machine_id=payload.machine_id,
        pubkey=payload.pubkey,
        device_token_hash=token_hash,
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
    stmt = select(Agent).order_by(Agent.created_at.desc())
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


@router.post("/{agent_id}/discover", response_model=DiscoverResponse)
async def discover_cameras(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """Trigger ONVIF discovery on the agent.

    The backend cannot reach the user's LAN directly; this endpoint records
    the request and returns whatever the agent has most recently advertised.
    Agents push discovery results via a separate authenticated endpoint
    (not yet implemented) — until then we return an empty list so the
    wizard falls back to manual brand-template entry.
    """
    await _load_agent_for_user(agent_id, user, db)
    return DiscoverResponse(cameras=[])


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

    site_stmt = select(Site).where(
        Site.id == payload.site_id, Site.org_id == agent.org_id
    )
    site = (await db.execute(site_stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="site not found in agent's org",
        )

    camera = Camera(
        org_id=agent.org_id,
        site_id=site.id,
        agent_id=agent.id,
        name=payload.name,
        ingest_mode="rtsp_pull",
        rtsp_url=payload.rtsp_url,
        enabled_events=["person", "vehicle", "intrusion"],
        detection_zones=[],
        sensitivity="medium",
        status="offline",
    )
    db.add(camera)
    await db.flush()
    return RegisterCameraResponse(camera_id=camera.id)
