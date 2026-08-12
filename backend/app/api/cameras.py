import asyncio
import base64
import json
import logging
import secrets
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_control import registry as control_registry
from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.camera import Camera
from app.models.chat_message import ChatMessage
from app.models.organization import Organization
from app.models.site import Site
from app.models.user import User
from app.schemas.camera import (
    CameraCreatedResponse,
    CameraResponse,
    CompileSequenceConversationResponse,
    CompileSequenceRequest,
    CompileSequenceResponse,
    CreateCameraRequest,
    LatestFrameResponse,
    StreamUrlResponse,
    UpdateCameraRequest,
    WebRTCAnswerResponse,
    WebRTCOfferRequest,
)
from app.services.digest.spend_tracker import SpendTracker
from app.services.gcs import fetch_gcs_object, gcs_blob_updated_at, sign_gcs_url
from app.services.sequence_compiler.deps import get_sequence_compiler_client, get_sequence_compiler_spend_tracker
from app.services.sequence_compiler.gemini_client import SequenceCompilerClient
from app.services.soft_delete_service import soft_delete_service
from app.services.stream_token import sign_stream_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

RTMP_INGEST_BASE = "rtmp://ingest.nightwatch.ai/live"

SEQUENCE_COMPILER_PURPOSE = "sequence_compiler"
SEQUENCE_COMPILER_MAX_TURNS = 5
APPROX_COST_PER_CALL_USD = 0.03

VALID_POSE_LABELS = {"standing", "bending", "crouching", "sitting", "reaching", None}


def _validate_step_sequence(step_sequence: list, detection_zones: list) -> None:
    if not step_sequence:
        return
    zone_names = {z.get("name") for z in detection_zones}
    for i, step in enumerate(step_sequence):
        if not step.get("name"):
            raise HTTPException(status_code=400, detail=f"step_sequence[{i}] is missing a name")
        zone = step.get("zone")
        if zone not in zone_names:
            raise HTTPException(
                status_code=400,
                detail=f"step_sequence[{i}] references unknown zone '{zone}' — must match an existing detection_zones name",
            )
        if step.get("pose") not in VALID_POSE_LABELS:
            raise HTTPException(
                status_code=400,
                detail=f"step_sequence[{i}] has invalid pose '{step.get('pose')}' — must be one of {sorted(p for p in VALID_POSE_LABELS if p)} or null",
            )


def _camera_query(user: User, include_deleted: bool = False):
    q = select(Camera)
    if not include_deleted:
        q = q.where(Camera.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Camera.org_id == user.org_id)
    return q


@router.get("", response_model=list[CameraResponse])
async def list_cameras(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    site_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
    include_deleted: bool = Query(False),
):
    q = _camera_query(user, include_deleted=include_deleted)
    if user.role == "super_admin" and org_id:
        q = q.where(Camera.org_id == org_id)
    if site_id:
        q = q.where(Camera.site_id == site_id)
    if status:
        q = q.where(Camera.status == status)

    result = await db.execute(q.order_by(Camera.created_at.desc()))
    return [CameraResponse.model_validate(c) for c in result.scalars().all()]


@router.post("", response_model=CameraCreatedResponse, status_code=201)
async def create_camera(
    body: CreateCameraRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    org_id = user.org_id
    if user.role == "super_admin":
        site_result = await db.execute(
            select(Site).where(Site.id == body.site_id, Site.deleted_at.is_(None))
        )
        site = site_result.scalar_one_or_none()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        org_id = site.org_id

    stream_key = None
    if body.ingest_mode in ("rtmp_push", "srt_push"):
        stream_key = f"nw_cam_{secrets.token_hex(16)}"

    _validate_step_sequence(body.step_sequence, body.detection_zones)

    camera = Camera(
        org_id=org_id,
        site_id=body.site_id,
        name=body.name,
        ingest_mode=body.ingest_mode,
        rtsp_url=body.rtsp_url,
        stream_key=stream_key,
        enabled_events=body.enabled_events,
        detection_zones=body.detection_zones,
        step_sequence=body.step_sequence,
        sensitivity=body.sensitivity,
        idle_fps=body.idle_fps,
        active_fps=body.active_fps,
    )
    db.add(camera)
    await db.flush()

    resp = CameraCreatedResponse(camera=CameraResponse.model_validate(camera))
    if stream_key:
        resp.ingest_endpoint = RTMP_INGEST_BASE
        resp.stream_key = stream_key
    return resp


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return CameraResponse.model_validate(camera)


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: uuid.UUID,
    body: UpdateCameraRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    updates = body.model_dump(exclude_unset=True)
    effective_zones = updates.get("detection_zones", camera.detection_zones)
    effective_sequence = updates.get("step_sequence", camera.step_sequence)
    _validate_step_sequence(effective_sequence, effective_zones)

    for field, value in updates.items():
        setattr(camera, field, value)
    await db.flush()
    return CameraResponse.model_validate(camera)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    await soft_delete_service.delete_camera(camera, db)


@router.post("/{camera_id}/restore", response_model=CameraResponse)
async def restore_camera(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = select(Camera).where(Camera.id == camera_id)
    if user.role != "super_admin":
        q = q.where(Camera.org_id == user.org_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.deleted_at is None:
        raise HTTPException(status_code=400, detail="Camera is not deleted")
    await soft_delete_service.restore_camera(camera, db)
    return CameraResponse.model_validate(camera)


@router.get("/{camera_id}/latest-frame", response_model=LatestFrameResponse)
async def get_camera_latest_frame(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    uri = f"gs://{settings.gcs_bucket}/latest/{camera_id}.webp"
    updated_at = gcs_blob_updated_at(uri)
    if updated_at is None:
        raise HTTPException(status_code=404, detail="no recent frame")

    signed_url = sign_gcs_url(uri, expires_in=300)
    if signed_url.startswith("gs://"):
        # V4 signing unavailable (e.g. local dev with ADC user credentials,
        # which have no private key to sign with) — inline the bytes instead.
        obj = fetch_gcs_object(uri)
        if obj is None:
            raise HTTPException(status_code=404, detail="no recent frame")
        data, content_type = obj
        signed_url = f"data:{content_type};base64,{base64.b64encode(data).decode()}"

    return LatestFrameResponse(url=signed_url, updated_at=updated_at)


@router.get("/{camera_id}/stream-url", response_model=StreamUrlResponse)
async def get_camera_stream_url(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    token, expires_at = sign_stream_token(str(camera_id))
    url = f"{settings.worker_stream_url}/stream/{camera_id}?token={token}"
    return StreamUrlResponse(url=url, expires_at=expires_at)


@router.post("/{camera_id}/webrtc-offer", response_model=WebRTCAnswerResponse)
async def camera_webrtc_offer(
    camera_id: uuid.UUID,
    body: WebRTCOfferRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Route a browser WebRTC offer to whichever transport currently serves
    this camera's live view.

    Edge-box path (new): if the camera's agent has an open control
    WebSocket, push the offer down that socket and relay back the answer.
    Worker-VM-fallback path (existing, unchanged): proxy the offer to the
    relay viewer endpoint. Returns an SDP answer when the camera is active
    on the relay. Returns 404 when the camera is not currently streaming via
    the relay (fall back to MJPEG on the client).
    """
    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    view_token, _ = sign_stream_token(str(camera_id), ttl_seconds=300)

    agent_id = camera.agent_id
    if agent_id and control_registry.get(agent_id) is not None:
        try:
            result = await control_registry.request_signal(
                agent_id,
                {
                    "type": "signal_offer",
                    "camera_id": str(camera_id),
                    "view_token": view_token,
                    "offer": body.offer,
                },
            )
        except (ConnectionError, asyncio.TimeoutError):
            raise HTTPException(status_code=503, detail="Edge box unreachable")
        return WebRTCAnswerResponse(answer=result["answer"])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.relay_webrtc_url}/view",
                json={
                    "camera_id": str(camera_id),
                    "view_token": view_token,
                    "offer": body.offer,
                },
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Relay unreachable")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Camera not on relay")
    if resp.status_code == 401:
        raise HTTPException(status_code=500, detail="Relay token validation failed")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Relay error")

    data = resp.json()
    return WebRTCAnswerResponse(answer=data["answer"])


async def _load_sequence_compiler_history(
    db: AsyncSession, org_id: uuid.UUID, camera_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[ChatMessage]:
    q = (
        select(ChatMessage)
        .where(
            ChatMessage.org_id == org_id,
            ChatMessage.camera_id == camera_id,
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.purpose == SEQUENCE_COMPILER_PURPOSE,
        )
        .order_by(ChatMessage.created_at)
    )
    return list((await db.execute(q)).scalars().all())


def _persist_sequence_compiler_message(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    camera_id: uuid.UUID,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
) -> None:
    db.add(
        ChatMessage(
            org_id=org_id,
            user_id=user_id,
            camera_id=camera_id,
            conversation_id=conversation_id,
            purpose=SEQUENCE_COMPILER_PURPOSE,
            role=role,
            content=content,
        )
    )


@router.post("/{camera_id}/compile-sequence", response_model=CompileSequenceResponse)
async def compile_sequence(
    camera_id: uuid.UUID,
    body: CompileSequenceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    compiler: SequenceCompilerClient = Depends(get_sequence_compiler_client),
    spend_tracker: SpendTracker = Depends(get_sequence_compiler_spend_tracker),
):
    """Conversational NL -> step_sequence draft compiler.

    Never persists a step_sequence or alert_rule directly — always returns a
    draft for the existing manual editor/validation to review before Save.
    Conversation history lives in chat_messages (purpose='sequence_compiler'),
    not in the request body, so each turn only sends the new message.
    """
    require_role(user, "admin")

    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    org_result = await db.execute(select(Organization).where(Organization.id == camera.org_id))
    organization = org_result.scalar_one_or_none()

    conversation_id = body.conversation_id or uuid.uuid4()
    history = (
        await _load_sequence_compiler_history(db, camera.org_id, camera_id, conversation_id)
        if body.conversation_id
        else []
    )

    user_turn_count = sum(1 for m in history if m.role == "user") + 1
    if user_turn_count > SEQUENCE_COMPILER_MAX_TURNS:
        raise HTTPException(status_code=400, detail="Conversation too long — start a new one.")
    force_draft = user_turn_count == SEQUENCE_COMPILER_MAX_TURNS

    _persist_sequence_compiler_message(
        db, camera.org_id, user.id, camera_id, conversation_id, "user", body.message
    )
    await db.flush()

    zone_names = [z.get("name") for z in (camera.detection_zones or [])]
    whatsapp_configured = bool(organization and organization.whatsapp_alert_contacts)

    charged = await spend_tracker.try_charge(camera.org_id, APPROX_COST_PER_CALL_USD)
    if not charged:
        reply = "Daily AI budget reached — build this manually, or try again tomorrow."
        _persist_sequence_compiler_message(
            db, camera.org_id, user.id, camera_id, conversation_id, "assistant", reply
        )
        return CompileSequenceResponse(conversation_id=conversation_id, type="question", message=reply)

    full_history = [{"role": m.role, "content": m.content} for m in history]
    full_history.append({"role": "user", "content": body.message})

    try:
        parsed = await compiler.turn(full_history, zone_names, whatsapp_configured, force_draft)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    except Exception as e:
        logger.warning(f"sequence compiler failed for camera {camera_id}: {e}")
        reply = "AI generation failed — try rephrasing, or build this manually."
        _persist_sequence_compiler_message(
            db, camera.org_id, user.id, camera_id, conversation_id, "assistant", reply
        )
        return CompileSequenceResponse(conversation_id=conversation_id, type="question", message=reply)

    if parsed.get("type") == "question":
        reply = parsed.get("message", "Could you clarify that?")
        _persist_sequence_compiler_message(
            db, camera.org_id, user.id, camera_id, conversation_id, "assistant", reply
        )
        return CompileSequenceResponse(conversation_id=conversation_id, type="question", message=reply)

    steps = parsed.get("steps", [])
    if not isinstance(steps, list):
        steps = []
    alert_rule = parsed.get("alert_rule")
    if not isinstance(alert_rule, dict):
        alert_rule = None
    warnings: list[str] = []

    if alert_rule and "whatsapp" in alert_rule.get("notify_channels", []):
        contacts = (organization.whatsapp_alert_contacts if organization else None) or []
        if contacts:
            alert_rule["notify_contacts"] = [{"type": "whatsapp", "value": c} for c in contacts]
        else:
            warnings.append(
                "No WhatsApp contacts configured for this org — add one in Settings before saving, "
                "or this channel won't notify anyone."
            )
    if alert_rule and "email" in alert_rule.get("notify_channels", []):
        warnings.append("Add a destination email address before saving.")
    if alert_rule and "webhook" in alert_rule.get("notify_channels", []):
        warnings.append("Add the destination URL for this webhook before saving.")
    if alert_rule:
        alert_rule["cameras"] = [str(camera_id)]

    try:
        _validate_step_sequence(steps, camera.detection_zones)
    except HTTPException as e:
        warnings.append(f"Generated draft has an issue: {e.detail}. Review and fix before saving.")

    _persist_sequence_compiler_message(
        db, camera.org_id, user.id, camera_id, conversation_id, "assistant", json.dumps(parsed)
    )

    return CompileSequenceResponse(
        conversation_id=conversation_id, type="draft", steps=steps, alert_rule=alert_rule, warnings=warnings
    )


@router.get("/{camera_id}/compile-sequence/{conversation_id}", response_model=CompileSequenceConversationResponse)
async def get_compile_sequence_conversation(
    camera_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    q = _camera_query(user).where(Camera.id == camera_id)
    result = await db.execute(q)
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    history = await _load_sequence_compiler_history(db, camera.org_id, camera_id, conversation_id)
    return CompileSequenceConversationResponse(
        messages=[{"role": m.role, "content": m.content} for m in history]
    )
