import uuid
from datetime import datetime, timezone, timedelta
import pytest

from app.models.digest import Digest
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_list_digests_requires_auth(client):
    resp = await client.get("/api/digests")
    assert resp.status_code in (401, 403, 422)


@pytest.mark.asyncio
async def test_list_digests_returns_only_org_digests(auth_client, db_session, test_org):
    other_org = Organization(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other_org)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(Digest(
        org_id=test_org.id, kind="on_demand",
        range_start=now - timedelta(hours=1), range_end=now,
        event_count=0,
        payload={
            "headline": "mine", "period": "p", "total_events": 0,
            "by_severity": {}, "narrative": "n", "highlights": [],
            "quiet_periods": [], "degraded": False,
        },
        delivered_channels=["dashboard"],
    ))
    db_session.add(Digest(
        org_id=other_org.id, kind="on_demand",
        range_start=now - timedelta(hours=1), range_end=now,
        event_count=0,
        payload={
            "headline": "theirs", "period": "p", "total_events": 0,
            "by_severity": {}, "narrative": "n", "highlights": [],
            "quiet_periods": [], "degraded": False,
        },
        delivered_channels=["dashboard"],
    ))
    await db_session.flush()

    resp = await auth_client.get("/api/digests")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["payload"]["headline"] == "mine"


@pytest.mark.asyncio
async def test_create_on_demand_rejects_range_too_long(auth_client):
    start = datetime.now(timezone.utc) - timedelta(days=10)
    end = datetime.now(timezone.utc)
    resp = await auth_client.post(
        "/api/digests",
        json={"start": start.isoformat(), "end": end.isoformat()},
    )
    assert resp.status_code == 400
    assert "range" in resp.json()["detail"].lower()
