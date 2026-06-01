import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.agent_pair_code import AgentPairCode
from app.models.user import User


@pytest.mark.asyncio
async def test_create_code(db_session, test_org):
    user = User(
        org_id=test_org.id,
        username=f"creator-{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("testpass"),
        name="Creator",
        role="owner",
    )
    db_session.add(user)
    await db_session.flush()

    code = AgentPairCode(
        code="123456",
        org_id=test_org.id,
        created_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(code)
    await db_session.flush()
    result = await db_session.execute(
        select(AgentPairCode).where(AgentPairCode.code == "123456")
    )
    assert result.scalar_one().org_id == test_org.id
