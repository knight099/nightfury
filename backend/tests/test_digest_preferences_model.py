import uuid
import datetime as dt
import pytest
from sqlalchemy import select
from app.models.organization import Organization
from app.models.digest_preferences import DigestPreferences


@pytest.mark.asyncio
async def test_digest_preferences_defaults(db_session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    prefs = DigestPreferences(org_id=org.id)
    db_session.add(prefs)
    await db_session.flush()

    result = await db_session.execute(
        select(DigestPreferences).where(DigestPreferences.org_id == org.id)
    )
    fetched = result.scalar_one()
    assert fetched.morning_enabled is True
    assert fetched.morning_local_time == dt.time(7, 0)
    assert fetched.evening_enabled is True
    assert fetched.evening_local_time == dt.time(19, 0)
    assert fetched.whatsapp_enabled is True
    assert fetched.email_enabled is False
