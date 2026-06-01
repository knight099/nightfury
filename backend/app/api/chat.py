"""Ask-Gemini chat endpoints.

Each user has their own conversations scoped to their org. Super-admin can
optionally scope a conversation to a specific org by passing ``org_id`` in the
request body; otherwise their conversations have ``org_id = NULL``.
"""

import logging
import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.models.camera import Camera
from app.models.chat_message import ChatMessage
from app.models.event import Event
from app.models.user import User
from app.schemas.chat import (
    ChatMessageDetail,
    ChatMessageResponse,
    ChatRequest,
    ConversationSummary,
)
from app.services.chat_service import (
    APPROX_COST_PER_CHAT_USD,
    ChatTurn,
    GeminiChatClient,
    get_chat_client,
)
from app.services.digest.spend_tracker import SpendTracker
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


HISTORY_LIMIT = 10
FALLBACK_REPLY = "I'm temporarily unable to respond"


# ─── Dependencies ────────────────────────────────────────────────────────────


async def _redis_dep():
    return await get_redis()


def get_chat_client_dep() -> GeminiChatClient:
    return get_chat_client()


async def _get_spend_tracker(redis=Depends(_redis_dep)) -> SpendTracker:
    return SpendTracker(
        redis_client=redis,
        daily_cap_usd=settings.digest_daily_spend_cap_usd,
    )


# ─── Helpers ────────────────────────────────────────────────────────────────


def _resolve_scope_org(current: User, body_org_id: uuid.UUID | None) -> uuid.UUID | None:
    """Determine the org_id for this chat operation.

    Regular users: forced to their own org_id (body override ignored).
    super_admin: respects body_org_id if supplied, else NULL.
    """
    if current.role == "super_admin":
        return body_org_id
    return current.org_id


async def _validate_camera(
    db: AsyncSession, camera_id: uuid.UUID, scope_org_id: uuid.UUID | None, current: User
) -> Camera:
    stmt = select(Camera).where(Camera.id == camera_id)
    if current.role != "super_admin":
        stmt = stmt.where(Camera.org_id == scope_org_id)
    elif scope_org_id is not None:
        stmt = stmt.where(Camera.org_id == scope_org_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Camera not found")
    return row


async def _validate_event(
    db: AsyncSession, event_id: uuid.UUID, scope_org_id: uuid.UUID | None, current: User
) -> Event:
    stmt = select(Event).where(Event.id == event_id)
    if current.role != "super_admin":
        stmt = stmt.where(Event.org_id == scope_org_id)
    elif scope_org_id is not None:
        stmt = stmt.where(Event.org_id == scope_org_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    return row


async def _load_history(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, limit: int
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


def _build_event_context(event: Event, camera_name: str | None) -> str:
    return (
        "Event context:\n"
        f"- timestamp: {event.timestamp.isoformat()}\n"
        f"- type: {event.event_type}\n"
        f"- severity: {event.severity}\n"
        f"- confidence: {event.confidence:.2f}\n"
        f"- description: {event.description}\n"
        f"- camera: {camera_name or 'unknown'}"
    )


async def _build_camera_context(db: AsyncSession, camera: Camera) -> str:
    # Recent event types (last 20)
    stmt = (
        select(Event.event_type)
        .where(Event.camera_id == camera.id)
        .order_by(Event.timestamp.desc())
        .limit(20)
    )
    types = [r for r in (await db.execute(stmt)).scalars().all()]
    return (
        "Camera context:\n"
        f"- name: {camera.name}\n"
        f"- status: {camera.status}\n"
        f"- recent_event_types: {sorted(set(types)) if types else 'none'}"
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("", response_model=ChatMessageResponse)
async def post_message(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
    chat_client: GeminiChatClient = Depends(get_chat_client_dep),
    spend: SpendTracker = Depends(_get_spend_tracker),
):
    scope_org_id = _resolve_scope_org(current, body.org_id)

    camera_obj: Camera | None = None
    event_obj: Event | None = None
    if body.camera_id is not None:
        camera_obj = await _validate_camera(db, body.camera_id, scope_org_id, current)
    if body.event_id is not None:
        event_obj = await _validate_event(db, body.event_id, scope_org_id, current)

    conversation_id = body.conversation_id or uuid.uuid4()

    # If continuing a conversation, ensure ownership.
    if body.conversation_id is not None:
        existing = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.user_id != current.id:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist user message
    user_msg = ChatMessage(
        org_id=scope_org_id,
        user_id=current.id,
        conversation_id=conversation_id,
        role="user",
        content=body.message,
        camera_id=body.camera_id,
        event_id=body.event_id,
    )
    db.add(user_msg)
    await db.flush()

    # Build context
    history = await _load_history(db, conversation_id, current.id, HISTORY_LIMIT + 1)
    # Exclude the just-added user message from history (it's the new turn).
    turn_history = [
        ChatTurn(role=m.role, content=m.content)
        for m in history
        if m.id != user_msg.id
    ][-HISTORY_LIMIT:]

    context_blocks: list[str] = []
    if event_obj is not None:
        cam_name = camera_obj.name if camera_obj else None
        if cam_name is None:
            cam_row = (
                await db.execute(select(Camera).where(Camera.id == event_obj.camera_id))
            ).scalar_one_or_none()
            cam_name = cam_row.name if cam_row else None
        context_blocks.append(_build_event_context(event_obj, cam_name))
    if camera_obj is not None:
        context_blocks.append(await _build_camera_context(db, camera_obj))

    # Spend cap (only meaningful when scoped to an org)
    if scope_org_id is not None:
        allowed = await spend.try_charge(scope_org_id, APPROX_COST_PER_CHAT_USD)
        if not allowed:
            raise HTTPException(status_code=429, detail="daily AI quota reached")

    logger.debug("chat: conversation=%s user=%s", conversation_id, current.id)

    try:
        result = await chat_client.reply(
            history=turn_history,
            user_message=body.message,
            context_blocks=context_blocks,
        )
        reply_text = result.text
        gemini_failed = False
    except Exception as e:
        logger.error("Gemini chat failed for user %s: %s", current.id, e)
        reply_text = FALLBACK_REPLY
        gemini_failed = True

    assistant_msg = ChatMessage(
        org_id=scope_org_id,
        user_id=current.id,
        conversation_id=conversation_id,
        role="assistant",
        content=reply_text,
        camera_id=body.camera_id,
        event_id=body.event_id,
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    if gemini_failed:
        # Persist the fallback so the conversation history is consistent,
        # then signal the client.
        raise HTTPException(status_code=503, detail=FALLBACK_REPLY)

    return ChatMessageResponse.model_validate(assistant_msg)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Find each user's conversation_id and its latest message timestamp.
    last_at_subq = (
        select(
            ChatMessage.conversation_id.label("conversation_id"),
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .where(ChatMessage.user_id == current.id)
        .group_by(ChatMessage.conversation_id)
        .order_by(func.max(ChatMessage.created_at).desc())
        .limit(50)
        .subquery()
    )

    # Join back to the row that matches that latest timestamp.
    stmt = (
        select(ChatMessage)
        .join(
            last_at_subq,
            and_(
                ChatMessage.conversation_id == last_at_subq.c.conversation_id,
                ChatMessage.created_at == last_at_subq.c.last_at,
            ),
        )
        .where(ChatMessage.user_id == current.id)
        .order_by(ChatMessage.created_at.desc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    # Deduplicate (same created_at edge case): keep first occurrence per conv.
    seen: set[uuid.UUID] = set()
    out: list[ConversationSummary] = []
    for r in rows:
        if r.conversation_id in seen:
            continue
        seen.add(r.conversation_id)
        out.append(
            ConversationSummary(
                conversation_id=r.conversation_id,
                last_message_at=r.created_at,
                last_content=(r.content or "")[:80],
                camera_id=r.camera_id,
                event_id=r.event_id,
            )
        )
    return out


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageDetail],
)
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Locate the conversation owner.
    owner_row = (
        await db.execute(
            select(ChatMessage.user_id)
            .where(ChatMessage.conversation_id == conversation_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner_row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if current.role != "super_admin" and owner_row != current.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [ChatMessageDetail.model_validate(r) for r in rows]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    owner_row = (
        await db.execute(
            select(ChatMessage.user_id)
            .where(ChatMessage.conversation_id == conversation_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner_row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if current.role != "super_admin" and owner_row != current.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.execute(
        delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    )
    await db.flush()
    return None
