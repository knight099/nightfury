import uuid
from unittest.mock import AsyncMock
import pytest

from app.services.digest.spend_tracker import SpendTracker


@pytest.mark.asyncio
async def test_under_cap_allows_and_records():
    redis = AsyncMock()
    redis.incrbyfloat.return_value = 0.10
    redis.expire.return_value = True

    tracker = SpendTracker(redis_client=redis, daily_cap_usd=1.0)
    org_id = uuid.uuid4()

    allowed = await tracker.try_charge(org_id, cost_usd=0.10)
    assert allowed is True
    redis.incrbyfloat.assert_awaited_once()
    redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_over_cap_refunds_and_denies():
    redis = AsyncMock()
    redis.incrbyfloat.side_effect = [1.20, 0.70]
    redis.expire.return_value = True

    tracker = SpendTracker(redis_client=redis, daily_cap_usd=1.0)
    org_id = uuid.uuid4()

    allowed = await tracker.try_charge(org_id, cost_usd=0.50)
    assert allowed is False
    assert redis.incrbyfloat.await_count == 2
