import json
import logging
from dataclasses import dataclass
from typing import Any, Sequence

from app.services.digest.compactor import EventCompact

logger = logging.getLogger(__name__)

# Approx cost (USD) per call. Tune after pilot. ~3¢ per digest is the planning estimate.
APPROX_COST_PER_CALL_USD = 0.03


SYSTEM_PROMPT = (
    "You are a security analyst summarizing CCTV events for a homeowner. "
    "Read the JSON list of events for a period and produce a calm, factual recap. "
    "Be specific about what was seen, when, and on which camera. "
    "Flag any unusual or repeated activity in 'highlights'. "
    "If activity was sparse, say so plainly."
)


SCHEMA_HINT = """
Respond ONLY with JSON matching this schema (no markdown, no commentary):
{
  "headline": string,
  "period": string,
  "total_events": number,
  "by_severity": object,
  "narrative": string,
  "highlights": [{"time": string, "camera_name": string, "why_notable": string}],
  "quiet_periods": [string]
}
""".strip()


@dataclass
class GeminiResult:
    payload: dict
    cost_usd: float


class GeminiDigestClient:
    def __init__(self, genai_client: Any, model: str = "gemini-2.5-flash"):
        self.client = genai_client
        self.model = model

    def _build_prompt(self, events: Sequence[EventCompact], period_label: str) -> str:
        events_json = json.dumps([e.__dict__ for e in events], default=str)
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"Period: {period_label}\n"
            f"Events ({len(events)}):\n{events_json}\n\n"
            f"{SCHEMA_HINT}"
        )

    async def summarize(self, events: Sequence[EventCompact], period_label: str) -> GeminiResult:
        prompt = self._build_prompt(events, period_label)
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
                payload = json.loads(text)
                return GeminiResult(payload=payload, cost_usd=APPROX_COST_PER_CALL_USD)
            except Exception as e:
                logger.warning("Gemini summarize attempt %d failed: %s", attempt, e)
                last_err = e
        assert last_err is not None
        raise last_err
