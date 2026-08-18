"""Ask-Gemini chat endpoints.

Each user has their own conversations scoped to their org. Super-admin can
optionally scope a conversation to a specific org by passing ``org_id`` in the
request body; otherwise their conversations have ``org_id = NULL``.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, permitted_site_ids, scope_to_sites
from app.services.digest.compactor import compact_events
from app.services.digest.sampler import sample_evenly
from app.core.redis import get_redis
from app.models.camera import Camera
from app.models.site import Site
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
        site_daily_cap_usd=settings.digest_site_daily_spend_cap_usd or None,
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
    stmt = select(Camera).where(Camera.id == camera_id, Camera.deleted_at.is_(None))
    if current.role != "super_admin":
        stmt = stmt.where(Camera.org_id == scope_org_id)
    elif scope_org_id is not None:
        stmt = stmt.where(Camera.org_id == scope_org_id)
    stmt = scope_to_sites(stmt, Camera.site_id, current)
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
    stmt = scope_to_sites(stmt, Event.site_id, current)
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


# Site-wide Ask ---------------------------------------------------------------

# Bounds what one question can pull into the prompt. The digest subsystem uses
# the same cap for the same reason: past a couple of hundred events the model
# gains nothing and the call gets expensive.
SITE_ASK_EVENT_CAP = 200
# Default lookback when the caller names a site but no window. A shift, near
# enough — long enough to cover "last night", short enough to stay answerable.
SITE_ASK_DEFAULT_HOURS = 12


async def _build_site_context(
    db: AsyncSession,
    site: Site,
    start: datetime | None,
    end: datetime | None,
) -> str:
    """Retrieve the site's events in a window and compact them for the prompt.

    This is the retrieval half of retrieve-then-generate. Without it the model
    answers "what happened near the food court last night?" from nothing but
    its own prior — which is to say, it invents an answer. Grounding it in the
    actual rows is the whole feature.
    """
    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(hours=SITE_ASK_DEFAULT_HOURS))

    stmt = (
        select(Event)
        .options(selectinload(Event.camera))
        .where(
            Event.site_id == site.id,
            Event.timestamp >= start,
            Event.timestamp <= end,
        )
        .order_by(Event.timestamp)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    window = f"{start.isoformat()} to {end.isoformat()}"
    if not rows:
        # Say so explicitly. An empty context block invites the model to fill
        # the silence; "there were none" is an answer it can repeat safely.
        return (
            f"Site context for '{site.name}':\n"
            f"- window: {window}\n"
            f"- events: NONE. Nothing was detected at this site in this window."
        )

    total = len(rows)
    sampled = sample_evenly(rows, cap=SITE_ASK_EVENT_CAP)
    compact = compact_events(
        [
            {
                "timestamp": e.timestamp,
                "camera_name": e.camera.name if e.camera else None,
                "event_type": e.event_type,
                "severity": e.severity,
                "description": e.description,
            }
            for e in sampled
        ]
    )
    lines = [
        f"- {c.time} | {c.camera_name} | {c.event_type} | {c.severity} | {c.description}"
        for c in compact
    ]
    note = (
        ""
        if total <= SITE_ASK_EVENT_CAP
        # The model must know it is looking at a sample, or it will answer
        # counting questions ("how many people?") from the truncated list as
        # though it were the whole set.
        else f"\n- NOTE: sampled {len(compact)} of {total} events evenly across the window; "
        "counts below are not exhaustive."
    )
    return (
        f"Site context for '{site.name}':\n"
        f"- window: {window}\n"
        f"- total_events: {total}{note}\n"
        f"- events:\n" + "\n".join(lines)
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
    site_obj = None
    if body.site_id is not None:
        site_stmt = select(Site).where(
            Site.id == body.site_id, Site.deleted_at.is_(None)
        )
        if scope_org_id is not None:
            site_stmt = site_stmt.where(Site.org_id == scope_org_id)
        site_stmt = scope_to_sites(site_stmt, Site.id, current)
        site_obj = (await db.execute(site_stmt)).scalar_one_or_none()
        if site_obj is None:
            raise HTTPException(status_code=404, detail="Site not found")

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
    if site_obj is not None:
        context_blocks.append(
            await _build_site_context(db, site_obj, body.start, body.end)
        )

    # Spend cap (only meaningful when scoped to an org)
    if scope_org_id is not None:
        # camera_obj carries the site when the chat is camera-scoped; a
        # site-less chat still charges the org cap alone.
        allowed = await spend.try_charge(
            scope_org_id,
            APPROX_COST_PER_CHAT_USD,
            # A site-wide Ask is charged to that site; a camera-scoped one to
            # the camera's site. Site-wide questions are the expensive kind
            # (they pull a window of events into the prompt), so they must
            # come out of that site's budget rather than the org's alone.
            site_id=(
                site_obj.id
                if site_obj is not None
                else camera_obj.site_id if camera_obj is not None else None
            ),
        )
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
