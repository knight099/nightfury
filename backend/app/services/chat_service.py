"""Ask-Gemini chat service: thin wrapper around the Gemini text API.

Reuses the same google.genai SDK and model name as the digest subsystem
(``gemini-2.5-flash``). Falls back gracefully when the SDK or API key are
unavailable so unit tests / local dev don't break on import.
"""

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from app.config import settings

logger = logging.getLogger(__name__)


# Approx cost per chat call (USD). Chat turns are smaller than digests; tune
# after pilot. Using a conservative half-cent default.
APPROX_COST_PER_CHAT_USD = 0.005

CHAT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are an AI assistant for Nightwatch, a CCTV event-intelligence platform. "
    "Answer concisely in <=200 words.\n"
    # Grounding rules. The context blocks are retrieved from the database
    # before this call; the whole point of retrieving them is that the answer
    # comes from them and not from the model's prior. A confidently invented
    # incident is far worse here than an unhelpful "nothing recorded" — a
    # security team may act on it.
    "Answer ONLY from the context provided below. If the context says no "
    "events were recorded, say exactly that — never invent or infer an "
    "incident that is not listed. If the context notes that events were "
    "sampled, do not give exact totals; say the count is approximate. "
    "When you refer to something that happened, cite the camera name and time "
    "from the context."
)


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ChatResult:
    text: str
    cost_usd: float


def _build_genai_client() -> Any:
    if not settings.gemini_api_key:
        return None
    try:
        from google import genai  # type: ignore
    except ImportError:
        logger.warning("google-genai package not installed; chat will degrade")
        return None
    return genai.Client(api_key=settings.gemini_api_key)


class GeminiChatClient:
    """Thin async wrapper that builds a single text generation call.

    The lower-level ``genai_client`` follows the same interface as the digest
    Gemini client — ``client.aio.models.generate_content(model=..., contents=...)``.
    """

    def __init__(self, genai_client: Any | None, model: str = CHAT_MODEL):
        self.client = genai_client
        self.model = model

    def _format_prompt(
        self,
        *,
        history: Sequence[ChatTurn],
        user_message: str,
        context_blocks: Sequence[str],
    ) -> str:
        parts: list[str] = [SYSTEM_PROMPT]
        for block in context_blocks:
            if block:
                parts.append(block)
        if history:
            transcript_lines = []
            for turn in history:
                role = "User" if turn.role == "user" else "Assistant"
                transcript_lines.append(f"{role}: {turn.content}")
            parts.append("Conversation so far:\n" + "\n".join(transcript_lines))
        parts.append(f"User: {user_message}")
        parts.append("Assistant:")
        return "\n\n".join(parts)

    async def reply(
        self,
        *,
        history: Sequence[ChatTurn],
        user_message: str,
        context_blocks: Sequence[str] = (),
    ) -> ChatResult:
        if self.client is None:
            raise RuntimeError(
                "Gemini client unavailable: GEMINI_API_KEY not set "
                "or google-genai package not installed"
            )
        prompt = self._format_prompt(
            history=history, user_message=user_message, context_blocks=context_blocks
        )
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Empty response from Gemini")
        return ChatResult(text=text, cost_usd=APPROX_COST_PER_CHAT_USD)


def get_chat_client() -> GeminiChatClient:
    """Build a chat client. Safe to call at request time; no global state."""
    return GeminiChatClient(genai_client=_build_genai_client())
