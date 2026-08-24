"""Assistant tool-calling endpoints.

Exposes the bounded Gemini tool-calling loop (Task 5) over HTTP, on top of
the same conversation model chat.py already uses (`chat_messages`) so
assistant conversations show up in the existing conversation-list endpoints
without any new persistence surface.

Error mapping is safety-critical here: SpendCapReached -> 429 and
RuntimeError / upstream google-genai errors (Gemini unavailable) -> 503
must stay distinct. The frontend uses that distinction to decide which
message to show above the fallback camera dashboard — collapsing the two
would collapse a physical-security UX guarantee, not just an HTTP status
code. An upstream Gemini quota/server error (google.genai.errors.APIError)
is deliberately mapped to 503, not 429: our 429 means "your org's daily AI
budget is exhausted," and labelling an upstream Gemini problem that way
would tell the user something false about their own account.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.config import settings
from app.models.chat_message import ChatMessage
from app.models.proposal import Proposal
from app.models.user import User
from app.schemas.assistant import (
    ApplyProposalResponse,
    AssistantMessageRequest,
    AssistantMessageResponse,
    ProposalResponse,
)
from app.services.assistant.gemini import AssistantGeminiClient, get_assistant_client
from app.services.assistant.loop import SpendCapReached, run_turn
from app.services.assistant.proposals import apply_proposal, reject_proposal
from app.services.assistant.registry import ToolContext
from app.services.chat_service import ChatTurn
from app.services.digest.spend_tracker import SpendTracker

logger = logging.getLogger(__name__)

# Defensive import: the google-genai package (or the API key) may be absent
# in some environments (see gemini.py's own graceful-degradation comment).
# An ImportError here at module load would take down the whole API, so we
# fall back to a tuple of no types — `isinstance(exc, ())` is always False,
# which just means the upstream-error branch below never matches and any
# genai-raised error falls through to the generic 500 path, same as today.
try:
    from google.genai.errors import APIError as GenaiAPIError  # type: ignore
except ImportError:  # pragma: no cover - package not installed in this env
    GenaiAPIError = ()  # type: ignore[assignment]

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

HISTORY_LIMIT = 10
# Distinguishes assistant tool-calling turns from plain Ask (purpose='qa')
# and the sequence compiler (purpose='sequence_compiler') in the shared
# chat_messages table — same pattern as cameras.py's SEQUENCE_COMPILER_PURPOSE.
ASSISTANT_PURPOSE = "assistant"


# ─── Dependencies ────────────────────────────────────────────────────────────


async def _redis_dep():
    return await get_redis()


def get_assistant_client_dep() -> AssistantGeminiClient:
    return get_assistant_client()


async def _get_spend_tracker(redis=Depends(_redis_dep)) -> SpendTracker:
    return SpendTracker(
        redis_client=redis,
        daily_cap_usd=settings.digest_daily_spend_cap_usd,
        site_daily_cap_usd=settings.digest_site_daily_spend_cap_usd or None,
    )


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _load_history(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, limit: int
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.user_id == user_id)
        .where(ChatMessage.purpose == ASSISTANT_PURPOSE)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/message", response_model=AssistantMessageResponse)
async def post_message(
    body: AssistantMessageRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
    client: AssistantGeminiClient = Depends(get_assistant_client_dep),
    spend: SpendTracker = Depends(_get_spend_tracker),
):
    conversation_id = body.conversation_id or uuid.uuid4()

    # Ownership check FIRST, before any Gemini call — never spend money on a
    # conversation the caller doesn't own. Mirrors chat.py:post_message.
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

    # Persist user message (same pattern as chat.py).
    user_msg = ChatMessage(
        org_id=current.org_id,
        user_id=current.id,
        conversation_id=conversation_id,
        role="user",
        content=body.message,
        purpose=ASSISTANT_PURPOSE,
    )
    db.add(user_msg)
    await db.flush()

    history_rows = await _load_history(db, conversation_id, current.id, HISTORY_LIMIT + 1)
    turn_history = [
        ChatTurn(role=m.role, content=m.content)
        for m in history_rows
        if m.id != user_msg.id
    ][-HISTORY_LIMIT:]

    ctx = ToolContext(
        db=db,
        user=current,
        org_id=current.org_id,
        conversation_id=conversation_id,
    )

    logger.debug("assistant: conversation=%s user=%s", conversation_id, current.id)

    try:
        result = await run_turn(
            client=client,
            spend=spend,
            ctx=ctx,
            history=turn_history,
            user_message=body.message,
        )
    except SpendCapReached:
        # Must be checked first and stay 429: this means OUR org's daily AI
        # budget is exhausted, which is meaningfully different from Gemini
        # itself being unavailable below.
        raise HTTPException(
            status_code=429,
            detail="Daily AI budget reached for your organisation.",
        )
    except RuntimeError as exc:  # Gemini unavailable / empty response
        raise HTTPException(status_code=503, detail=str(exc))
    except GenaiAPIError as exc:
        # Upstream google-genai failure (e.g. Gemini's OWN quota exhausted,
        # a ClientError with status 429, or a ServerError). This is NOT the
        # org's spend cap, so it must never be reported as 429 — the
        # frontend renders that exact status as "your organisation's daily
        # AI budget is reached," which would be false here. 503 ("assistant
        # temporarily unavailable") is accurate for any upstream failure and
        # still triggers the same fallback-dashboard behavior as RuntimeError.
        logger.warning("assistant: upstream Gemini error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Assistant is temporarily unavailable. Please try again shortly.",
        )

    assistant_msg = ChatMessage(
        org_id=current.org_id,
        user_id=current.id,
        conversation_id=conversation_id,
        role="assistant",
        content=result.text,
        purpose=ASSISTANT_PURPOSE,
    )
    db.add(assistant_msg)
    await db.flush()

    proposals: list[ProposalResponse] = []
    if result.proposal_ids:
        prop_rows = (
            await db.execute(
                select(Proposal).where(Proposal.id.in_(result.proposal_ids))
            )
        ).scalars().all()
        proposals = [ProposalResponse.model_validate(p) for p in prop_rows]

    return AssistantMessageResponse(
        conversation_id=conversation_id,
        text=result.text,
        proposals=proposals,
        navigate=result.navigate,
        stopped_early=result.stopped_early,
    )


@router.post("/proposals/{proposal_id}/apply", response_model=ApplyProposalResponse)
async def apply_proposal_route(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    result = await apply_proposal(db, current, proposal_id)
    created_id = result.get("id")
    return ApplyProposalResponse(
        status=result["status"],
        created_id=uuid.UUID(created_id) if created_id else None,
    )


@router.post("/proposals/{proposal_id}/reject", status_code=204)
async def reject_proposal_route(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await reject_proposal(db, current, proposal_id)
    return None
