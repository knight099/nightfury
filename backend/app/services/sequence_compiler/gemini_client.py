import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You help configure a camera's step-sequence tracker through conversation.
A step_sequence is an ordered list of steps; each step has a zone (must be one of the
camera's existing zone names, given below — never invent one), an optional pose (must be
exactly one of: standing, bending, crouching, sitting, reaching, or null for "any pose"),
and an optional max_seconds timeout.

If the user's request implies they want to be notified (e.g. "text the manager", "email
security", "call our system"), also draft an alert_rule: event_types drawn from
{step_skipped, step_timeout, sequence_completed}, min_severity, and notify_channels drawn
from {whatsapp, email, webhook}. You cannot invent a phone number, email address, or URL —
only infer the channel type from language.

If the description is genuinely ambiguous (an unclear zone reference, a notification
channel with no clear target and no existing default) respond with a clarifying question:
{"type": "question", "message": "<one specific question>"}

Otherwise respond with the final draft:
{"type": "draft", "steps": [...], "alert_rule": {...} | null}

Respond ONLY with JSON, no markdown, no commentary. Ask at most one question at a time."""


class SequenceCompilerClient:
    """Conversational NL -> step_sequence draft compiler.

    Uses a single plain-text prompt (contents=<string>) rather than a
    multi-part role-tagged contents list, matching the only proven
    google-genai usage pattern already in this codebase
    (GeminiDigestClient) — the conversation history is rendered into the
    prompt text itself instead of relying on an unverified contents shape.
    """

    def __init__(self, genai_client: Any, model: str = "gemini-2.5-flash"):
        self.client = genai_client
        self.model = model

    def _build_prompt(self, messages: list[dict], zone_names: list[str], whatsapp_configured: bool, force_draft: bool) -> str:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        context = (
            f"Available zones for this camera: {zone_names}\n"
            f"Org has WhatsApp contacts configured: {whatsapp_configured}\n"
        )
        if force_draft:
            context += "\nThis is the final turn. Respond with a draft now, not a question.\n"
        return f"{SYSTEM_PROMPT}\n\n{context}\nConversation so far:\n{transcript}"

    async def turn(
        self,
        messages: list[dict],
        zone_names: list[str],
        whatsapp_configured: bool,
        force_draft: bool = False,
    ) -> dict:
        prompt = self._build_prompt(messages, zone_names, whatsapp_configured, force_draft)
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                text = response.text.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.startswith("json"):
                        text = text[4:].lstrip()
                return json.loads(text)
            except Exception as e:
                logger.warning("Sequence compiler turn attempt %d failed: %s", attempt, e)
                last_err = e
        assert last_err is not None
        raise last_err
