"""Internal endpoints called by stream workers (authenticated via API key)."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import verify_worker_key
from app.models.camera import Camera
from app.models.event import Event
from app.models.organization import Organization
from app.schemas.assignment import Assignment, AssignmentsResponse
from app.schemas.event import CreateEventRequest, EventResponse
from app.schemas.heartbeat import HeartbeatRequest
from app.services.alert_service import alert_service
from app.services.agent_auth import resolve_agent_by_token
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
    worker_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> AssignmentsResponse:
    """Return all cameras the worker should be processing.

    For MVP, `worker_id` is accepted but ignored — every worker pulls the full
    set of cameras whose ingest_mode is supported by the worker pipeline.
    """
    stmt = (
        select(Camera, Organization.timezone)
        .join(Organization, Camera.org_id == Organization.id)
        .where(
            Camera.ingest_mode.in_(["rtsp_pull", "rtmp_push"]),
            Camera.deleted_at.is_(None),
            Organization.deleted_at.is_(None),
        )
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
            sensitivity=camera.sensitivity,
            idle_fps=camera.idle_fps,
            active_fps=camera.active_fps,
            timezone=tz or "UTC",
        )
        for camera, tz in rows
    ]
    return AssignmentsResponse(assignments=assignments)


@router.post("/heartbeat", status_code=200)
async def worker_heartbeat(body: HeartbeatRequest, db: AsyncSession = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    camera_id = data.get("camera_id")
    if not camera_id:
        return {"status": "ok"}

    result = await db.execute(
        select(Camera).where(Camera.id == uuid.UUID(camera_id), Camera.deleted_at.is_(None))
    )
    camera = result.scalar_one_or_none()
    if camera:
        camera.status = data.get("status", "online")
        camera.last_frame_at = datetime.now(timezone.utc)
        camera.worker_id = data.get("worker_id")
        await db.flush()

    # Log pipeline health if present
    if pipeline := data.get("pipeline"):
        logger.info("pipeline health for camera %s: %s", camera_id, pipeline)

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
