"""Gemini tool-calling client for the Nightwatch assistant.

Mirrors ``chat_service.py``'s graceful-degradation pattern: building the
client at import/request time must never raise, even when ``GEMINI_API_KEY``
is unset or the ``google-genai`` package is missing. The client only raises
(``RuntimeError``) when ``generate()`` is actually called with no usable
client — Task 6 maps that to an HTTP 503, which is what triggers the
frontend's fallback to a plain dashboard.
"""

import logging
from typing import Any

from app.config import settings
from app.services.assistant.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# Approx cost per assistant turn (USD), including tool calls. Tune after
# pilot. Matches the conservative half-cent default used by chat/digests.
APPROX_COST_PER_TURN_USD = 0.005

ASSISTANT_MODEL = "gemini-2.5-flash"


def _build_genai_client() -> Any:
    if not settings.gemini_api_key:
        return None
    try:
        from google import genai  # type: ignore
    except ImportError:
        logger.warning(
            "google-genai package not installed; assistant will degrade"
        )
        return None
    return genai.Client(api_key=settings.gemini_api_key)


class AssistantGeminiClient:
    """Thin async wrapper around Gemini's tool-calling generate_content call."""

    def __init__(self, genai_client: Any | None, model: str = ASSISTANT_MODEL):
        self.client = genai_client
        self.model = model

    async def generate(self, *, contents: list, tools: list[dict]) -> Any:
        if self.client is None:
            raise RuntimeError(
                "Gemini client unavailable: GEMINI_API_KEY not set "
                "or google-genai package not installed"
            )
        from google.genai import types  # type: ignore

        return await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(function_declarations=tools)],
            ),
        )


def get_assistant_client() -> AssistantGeminiClient:
    """Build an assistant client. Safe to call at request time; no global state."""
    return AssistantGeminiClient(genai_client=_build_genai_client())
