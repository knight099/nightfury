"""Internal endpoints called by stream workers (authenticated via API key)."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import verify_worker_key
from app.models.agent import Agent
from app.models.camera import Camera
from app.models.event import Event
from app.models.footfall_count import FootfallCount
from app.models.organization import Organization
from app.schemas.assignment import Assignment, AssignmentsResponse
from app.schemas.event import CreateEventRequest, EventResponse
from app.schemas.heartbeat import HeartbeatRequest
from app.services.alert_service import alert_service
from app.services.agent_auth import resolve_agent_by_token
from app.services.camera_placement import reconcile_site
from app.services.gcs import sign_gcs_url
from app.ws.events import broadcast_to_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_worker_key)])


@router.post("/events", response_model=dict, status_code=201)
async def ingest_event(body: CreateEventRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Camera).where(Camera.id == body.camera_id, Camera.deleted_at.is_(None))
    )
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    event = Event(
        org_id=camera.org_id,
        camera_id=camera.id,
        site_id=camera.site_id,
        timestamp=body.timestamp,
        event_type=body.event_type,
        confidence=body.confidence,
        severity=body.severity,
        description=body.description,
        bounding_boxes=body.bounding_boxes,
        snapshot_url=body.snapshot_url,
        clip_url=body.clip_url,
        ai_model=body.ai_model,
        ai_response_raw=body.ai_response_raw,
        metadata_extra=body.metadata_extra,
    )
    db.add(event)
    await db.flush()

    alerts_triggered = await alert_service.evaluate_event(event, db)

    try:
        payload = EventResponse.model_validate(event).model_dump(mode="json")
        payload["snapshot_url"] = sign_gcs_url(event.snapshot_url)
        if event.clip_url:
            payload["clip_url"] = sign_gcs_url(event.clip_url)
        message = {"type": "event.created", "event": payload}
        await broadcast_to_org(str(event.org_id), message)
        await broadcast_to_org("all", message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws broadcast failed for event %s: %s", event.id, exc)

    return {"event_id": str(event.id), "alerts_triggered": alerts_triggered}


@router.get("/assignments", response_model=AssignmentsResponse)
async def list_assignments(
    request: Request,
    response: Response,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
):
    """Return the cameras THIS caller should be processing.

    Scoping is derived from the authenticated principal that
    ``verify_worker_key`` already resolved — never from a client-supplied
    identifier. An agent's device token proves which agent (and which org) is
    asking; trusting a ``worker_id`` query parameter for that would let any
    valid token read any other org's cameras.

    Two principals, two behaviours:

    * ``agent`` (edge box, the default deployment) — only cameras placed on
      this agent by the placement reconciler. Supports If-None-Match/304.
    * ``worker`` (cloud-VM fallback) — the org-wide list, as before. That path
      has no per-agent placement and no agent row to scope by, so its previous
      behaviour is preserved deliberately rather than by omission.
    """
    principal = getattr(request.state, "internal_principal", None) or {}

    stmt = (
        select(Camera, Organization.timezone)
        .join(Organization, Camera.org_id == Organization.id)
        .where(
            Camera.ingest_mode.in_(["rtsp_pull", "rtmp_push"]),
            Camera.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
        )
    )

    assignment_version: int | None = None
    if principal.get("kind") == "agent":
        agent_id = principal["agent_id"]
        agent = (
            await db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=401, detail="unknown agent")

        assignment_version = agent.assignment_version
        etag = f'"{agent_id}:{assignment_version}"'
        response.headers["ETag"] = etag
        if if_none_match == etag:
            # Returned as a bare Response, not a serialised model: a 304 must
            # not carry a body, and returning the model here would attach one
            # (with a Content-Length some proxies reject).
            return Response(status_code=304, headers={"ETag": etag})

        stmt = stmt.where(
            Camera.org_id == agent.org_id,
            Camera.agent_id == agent_id,
        )

    result = await db.execute(stmt)
    rows = result.all()

    assignments = [
        Assignment(
            camera_id=camera.id,
            org_id=camera.org_id,
            name=camera.name,
            ingest_mode=camera.ingest_mode,
            rtsp_url=camera.rtsp_url,
            stream_key=camera.stream_key,
            enabled_events=list(camera.enabled_events or []),
            detection_zones=list(camera.detection_zones or []),
            step_sequence=list(camera.step_sequence or []),
            counting_lines=list(camera.counting_lines or []),
            sensitivity=camera.sensitivity,
            idle_fps=camera.idle_fps,
            active_fps=camera.active_fps,
            timezone=tz or "UTC",
        )
        for camera, tz in rows
    ]
    return AssignmentsResponse(
        assignments=assignments, assignment_version=assignment_version
    )


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


@router.post("/heartbeat", status_code=200)
async def worker_heartbeat(
    request: Request, body: HeartbeatRequest, db: AsyncSession = Depends(get_db)
):
    """Accept a batched agent heartbeat, or a legacy single-camera one.

    Also the natural place to reconcile placement: it is already a write path,
    it fires every ~30s, and it carries the agent's current capacity. That
    makes the fleet self-healing — a site with unassigned cameras and a box
    with spare capacity resolves itself on the next beat, with no operator
    action and no separate scheduler.
    """
    principal = getattr(request.state, "internal_principal", None) or {}
    now = datetime.now(timezone.utc)

    # Normalise both wire shapes into one list.
    if body.cameras is not None:
        reports = [(c.camera_id, c.status) for c in body.cameras]
    elif body.camera_id:
        reports = [(body.camera_id, body.status or "online")]
    else:
        reports = []

    rejected = {r for r in (body.rejected_cameras or [])}
    footfall_by_camera = {
        c.camera_id: c.footfall for c in (body.cameras or []) if c.footfall
    }

    camera_ids = [cid for cid in (_parse_uuid(c) for c, _ in reports) if cid is not None]
    cameras_by_id: dict[uuid.UUID, Camera] = {}
    if camera_ids:
        rows = await db.execute(
            select(Camera).where(Camera.id.in_(camera_ids), Camera.deleted_at.is_(None))
        )
        cameras_by_id = {c.id: c for c in rows.scalars().all()}

    for raw_id, status_value in reports:
        camera_id = _parse_uuid(raw_id)
        if camera_id is None:
            continue
        camera = cameras_by_id.get(camera_id)
        if camera is None:
            continue
        # An agent that could not start a camera must not also mark it online.
        camera.status = "unassigned" if raw_id in rejected else status_value
        if raw_id not in rejected:
            camera.last_frame_at = now
        camera.worker_id = body.worker_id

    # Persist footfall buckets. Rows are only written for lines that actually
    # counted something, so an idle camera costs no storage.
    for raw_id, lines in footfall_by_camera.items():
        camera_id = _parse_uuid(raw_id)
        camera = cameras_by_id.get(camera_id) if camera_id else None
        if camera is None:
            continue
        for line_name, counts in (lines or {}).items():
            c_in = int(counts.get("in", 0) or 0)
            c_out = int(counts.get("out", 0) or 0)
            if c_in == 0 and c_out == 0:
                continue
            db.add(
                FootfallCount(
                    org_id=camera.org_id,
                    site_id=camera.site_id,
                    camera_id=camera.id,
                    line_name=str(line_name)[:100],
                    bucket_at=now,
                    count_in=c_in,
                    count_out=c_out,
                )
            )

    agent_id = principal.get("agent_id")
    agent: Agent | None = None
    if agent_id is not None:
        agent = (
            await db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()

    if agent is not None:
        agent.last_seen_at = now
        # Recovery from failover. The fleet-health sweep marks a silent agent
        # "offline", which makes placement treat it as unusable. Without this
        # line that flip is permanent: the box would keep heartbeating, keep
        # being skipped by the reconciler, and never get cameras back.
        if agent.status == "offline":
            logger.info("agent %s is reporting again; returning it to service", agent.id)
            agent.status = "online"
        if body.capacity_cameras is not None:
            agent.capacity_cameras = body.capacity_cameras
        if body.capacity_source is not None:
            agent.capacity_source = body.capacity_source
        if body.load_state is not None:
            agent.load_state = body.load_state
        agent.load_reason = body.load_reason
        # An agent that has never had a site (paired before this column
        # existed, or paired before any camera was registered) adopts the site
        # of the cameras it is actually serving.
        if agent.site_id is None:
            for camera in cameras_by_id.values():
                if camera.agent_id == agent.id:
                    agent.site_id = camera.site_id
                    break

    await db.flush()

    # Reconcile after the capacity update above, so a capacity change takes
    # effect on the same beat that reported it.
    #
    # Batched heartbeats only. A legacy agent posts once PER CAMERA, so
    # reconciling here would fire one placement pass per camera per round —
    # hundreds per 30s on a large box, for a deployment shape that is
    # single-agent anyway and has nothing to redistribute.
    if agent is not None and body.cameras is not None:
        try:
            await reconcile_site(db, agent.org_id, agent.site_id)
        except Exception as exc:  # noqa: BLE001
            # Placement is an optimisation over an already-working system;
            # a failure here must never cost us the health update.
            logger.warning("placement reconcile failed for agent %s: %s", agent.id, exc)

    if body.pipeline:
        logger.info("pipeline health from worker %s: %s", body.worker_id, body.pipeline)

    return {"status": "ok"}


class VerifyTokenReq(BaseModel):
    token: str


class VerifyTokenResp(BaseModel):
    org_id: str
    agent_id: str


@router.post("/agents/verify-token", response_model=VerifyTokenResp)
async def verify_agent_token(
    body: VerifyTokenReq, db: AsyncSession = Depends(get_db)
) -> VerifyTokenResp:
    """Verify an agent's device token (called by relay)."""
    agent = await resolve_agent_by_token(db, body.token)
    if agent is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    return VerifyTokenResp(org_id=str(agent.org_id), agent_id=str(agent.id))
