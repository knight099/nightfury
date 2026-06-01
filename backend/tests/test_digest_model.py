import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select
from app.models.organization import Organization
from app.models.digest import Digest


@pytest.mark.asyncio
async def test_digest_persistence_roundtrip(db_session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    digest = Digest(
        org_id=org.id,
        kind="scheduled_morning",
        range_start=now - timedelta(hours=8),
        range_end=now,
        event_count=12,
        payload={"headline": "Quiet night", "narrative": "Nothing of note."},
        delivered_channels=["whatsapp", "dashboard"],
    )
    db_session.add(digest)
    await db_session.flush()

    result = await db_session.execute(select(Digest).where(Digest.org_id == org.id))
    fetched = result.scalar_one()
    assert fetched.kind == "scheduled_morning"
    assert fetched.event_count == 12
    assert fetched.payload["headline"] == "Quiet night"
    assert "whatsapp" in fetched.delivered_channels
    assert fetched.created_at is not None
