from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest


@pytest.mark.asyncio
async def test_on_demand_rate_limit_returns_429(auth_client, monkeypatch):
    # Patch the imported settings reference inside the api module
    from app.api import digests as digests_api

    class _S:
        digest_max_range_days = 7
        digest_on_demand_per_user_hourly_limit = 1

    monkeypatch.setattr(digests_api, "settings", _S)

    start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    end = datetime.now(timezone.utc).isoformat()

    # Stub the service so we don't call Gemini
    from app.services.digest.service import DigestService
    from app.models.digest import Digest

    async def fake_generate(self, *, org_id, kind, start, end, **kwargs):
        return Digest(
            id=__import__("uuid").uuid4(),
            org_id=org_id,
            kind=kind,
            range_start=start,
            range_end=end,
            event_count=0,
            payload={
                "headline": "x", "period": "x", "total_events": 0,
                "by_severity": {}, "narrative": "x", "highlights": [],
                "quiet_periods": [], "degraded": False,
            },
            delivered_channels=["dashboard"],
            created_at=datetime.now(timezone.utc),
        )

    with patch.object(DigestService, "generate", new=fake_generate):
        r1 = await auth_client.post(
            "/api/digests", json={"start": start, "end": end}
        )
        assert r1.status_code in (200, 201), r1.text
        r2 = await auth_client.post(
            "/api/digests", json={"start": start, "end": end}
        )
        assert r2.status_code == 429, r2.text
