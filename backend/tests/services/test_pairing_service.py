import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.agent_pair_code import AgentPairCode
from app.services.pairing_service import PairingService


@pytest.mark.asyncio
async def test_mint_code_returns_six_digits(db_session, test_org, test_user):
    service = PairingService(db_session)
    code = await service.mint_code(test_org.id, test_user.id)
    assert isinstance(code, str)
    assert re.fullmatch(r"\d{6}", code)


@pytest.mark.asyncio
async def test_mint_code_persists_with_ttl(db_session, test_org, test_user):
    service = PairingService(db_session)
    before = datetime.now(timezone.utc)
    code = await service.mint_code(test_org.id, test_user.id)
    after = datetime.now(timezone.utc)

    result = await db_session.execute(
        select(AgentPairCode).where(AgentPairCode.code == code)
    )
    row = result.scalar_one()
    assert row.org_id == test_org.id
    assert row.created_by == test_user.id
    assert row.consumed_at is None
    expected_low = before + timedelta(seconds=595)
    expected_high = after + timedelta(seconds=605)
    assert expected_low <= row.expires_at <= expected_high


@pytest.mark.asyncio
async def test_get_code_returns_row_or_none(db_session, test_org, test_user):
    service = PairingService(db_session)
    code = await service.mint_code(test_org.id, test_user.id)
    found = await service.get_code(code)
    assert found is not None
    assert found.code == code
    missing = await service.get_code("000000")
    assert missing is None


@pytest.mark.asyncio
async def test_redeem_valid_code_returns_org_id(db_session, test_org, test_user):
    service = PairingService(db_session)
    code = await service.mint_code(test_org.id, test_user.id)
    org_id = await service.redeem_code(code)
    assert org_id == test_org.id

    result = await db_session.execute(
        select(AgentPairCode).where(AgentPairCode.code == code)
    )
    row = result.scalar_one()
    assert row.consumed_at is not None


@pytest.mark.asyncio
async def test_redeem_unknown_code_raises(db_session):
    service = PairingService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await service.redeem_code("999999")


@pytest.mark.asyncio
async def test_redeem_consumed_code_raises(db_session, test_org, test_user):
    service = PairingService(db_session)
    code = await service.mint_code(test_org.id, test_user.id)
    await service.redeem_code(code)
    with pytest.raises(ValueError, match="consumed"):
        await service.redeem_code(code)


@pytest.mark.asyncio
async def test_redeem_expired_code_raises(db_session, test_org, test_user):
    service = PairingService(db_session)
    expired = AgentPairCode(
        code="111111",
        org_id=test_org.id,
        created_by=test_user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(expired)
    await db_session.flush()
    with pytest.raises(ValueError, match="expired"):
        await service.redeem_code("111111")
