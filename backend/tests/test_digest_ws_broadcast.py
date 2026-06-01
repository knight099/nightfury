import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytest

from app.services.digest.service import DigestService
from app.services.digest.gemini_client import GeminiResult
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_digest_generation_emits_ws_broadcast(db_session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    gemini = MagicMock()
    gemini.summarize = AsyncMock(return_value=GeminiResult(
        payload={"headline": "x", "period": "x", "total_events": 0,
                 "by_severity": {}, "narrative": "x", "highlights": [], "quiet_periods": []},
        cost_usd=0.0,
    ))
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=False)

    with patch("app.services.digest.service.broadcast_to_org", new_callable=AsyncMock) as bc:
        svc = DigestService(
            db=db_session, gemini=gemini, spend_tracker=spend,
            notification=notif, dashboard_base_url="https://x",
        )
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=1)
        await svc.generate(org_id=org.id, kind="on_demand", start=start, end=end)
        assert bc.await_count == 1
        args, _ = bc.call_args
        assert args[1]["type"] == "digest.ready"
