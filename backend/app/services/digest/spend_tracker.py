import datetime as dt
import uuid
from typing import Protocol


class _RedisLike(Protocol):
    async def incrbyfloat(self, key: str, amount: float) -> float: ...
    async def expire(self, key: str, seconds: int) -> bool: ...


class SpendTracker:
    """Per-org daily Gemini spend cap, backed by Redis."""

    def __init__(self, redis_client: _RedisLike, daily_cap_usd: float):
        self.redis = redis_client
        self.cap = daily_cap_usd

    def _key(self, org_id: uuid.UUID, day: dt.date) -> str:
        return f"digest:spend:{org_id}:{day.isoformat()}"

    async def try_charge(self, org_id: uuid.UUID, cost_usd: float) -> bool:
        """Atomically charge `cost_usd` to the org's daily counter.

        If the resulting total exceeds the cap, refund and return False.
        Otherwise return True. Counter expires at end of UTC day.
        """
        today = dt.datetime.now(dt.timezone.utc).date()
        key = self._key(org_id, today)
        new_total = await self.redis.incrbyfloat(key, cost_usd)
        await self.redis.expire(key, 90_000)
        if new_total > self.cap:
            await self.redis.incrbyfloat(key, -cost_usd)
            return False
        return True
