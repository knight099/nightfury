import uuid
import pytest
from sqlalchemy import select
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_organization_has_default_timezone(db_session):
    slug = f"acme-{uuid.uuid4().hex[:6]}"
    org = Organization(name="Acme", slug=slug)
    db_session.add(org)
    await db_session.flush()

    result = await db_session.execute(
        select(Organization).where(Organization.slug == slug)
    )
    fetched = result.scalar_one()
    assert fetched.timezone == "Asia/Kolkata"
    assert fetched.whatsapp_number is None
