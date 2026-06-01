from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.digest.gemini_client import GeminiDigestClient, GeminiResult
from app.services.digest.compactor import EventCompact


def _fake_compact():
    return [
        EventCompact(
            time="2026-05-28T01:00:00+00:00",
            camera_name="Front",
            event_type="motion",
            severity="medium",
            description="A person near the gate",
            confidence=0.9,
        )
    ]


@pytest.mark.asyncio
async def test_summarize_returns_structured_payload():
    fake_response = MagicMock()
    fake_response.text = (
        '{"headline":"All clear","period":"Last night",'
        '"total_events":1,"by_severity":{"medium":1},'
        '"narrative":"A person was seen near the gate.",'
        '"highlights":[{"time":"2026-05-28T01:00:00+00:00",'
        '"camera_name":"Front","why_notable":"only event"}],'
        '"quiet_periods":[]}'
    )
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(return_value=fake_response)

    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    result = await client.summarize(_fake_compact(), period_label="Last night")

    assert isinstance(result, GeminiResult)
    assert result.payload["headline"] == "All clear"
    assert result.payload["total_events"] == 1
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_summarize_retries_once_on_failure():
    fake_response = MagicMock()
    fake_response.text = '{"headline":"x","period":"x","total_events":0,"by_severity":{},"narrative":"x","highlights":[],"quiet_periods":[]}'
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("boom"), fake_response]
    )

    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    result = await client.summarize(_fake_compact(), period_label="x")
    assert result.payload["headline"] == "x"
    assert fake_genai.aio.models.generate_content.await_count == 2


@pytest.mark.asyncio
async def test_summarize_raises_after_two_failures():
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("a"), RuntimeError("b")]
    )
    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    with pytest.raises(RuntimeError):
        await client.summarize(_fake_compact(), period_label="x")
