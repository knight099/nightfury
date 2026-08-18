import datetime as dt
import uuid
from typing import Protocol


class _RedisLike(Protocol):
    async def incrbyfloat(self, key: str, amount: float) -> float: ...
    async def expire(self, key: str, seconds: int) -> bool: ...


class SpendTracker:
    """Daily Gemini spend cap, backed by Redis.

    Charges against **two** counters when a site is known: the org's cap and
    that site's own cap.

    An org-only cap was sized for a home box with one site. On an estate it
    means one busy floor can exhaust the whole budget and silently degrade
    every other floor to local-detection-only for the rest of the day — the
    failure is real, and worse, it appears somewhere other than where it was
    caused. The per-site cap contains the blast radius to the site that spent
    the money.

    The org cap still applies on top, so per-site budgets can never sum to
    more than the org is willing to spend.
    """

    def __init__(
        self,
        redis_client: _RedisLike,
        daily_cap_usd: float,
        site_daily_cap_usd: float | None = None,
    ):
        self.redis = redis_client
        self.cap = daily_cap_usd
        # None disables the per-site cap, preserving the original behaviour
        # for deployments that have not configured one.
        self.site_cap = site_daily_cap_usd

    def _key(self, org_id: uuid.UUID, day: dt.date) -> str:
        return f"digest:spend:{org_id}:{day.isoformat()}"

    def _site_key(self, site_id: uuid.UUID, day: dt.date) -> str:
        return f"digest:spend:site:{site_id}:{day.isoformat()}"

    async def _charge(self, key: str, cost_usd: float, cap: float) -> bool:
        new_total = await self.redis.incrbyfloat(key, cost_usd)
        await self.redis.expire(key, 90_000)
        if new_total > cap:
            await self.redis.incrbyfloat(key, -cost_usd)
            return False
        return True

    async def try_charge(
        self,
        org_id: uuid.UUID,
        cost_usd: float,
        site_id: uuid.UUID | None = None,
    ) -> bool:
        """Atomically charge `cost_usd`. Returns False if any cap would break.

        The site counter is charged FIRST so that a site which is already over
        budget never touches the org counter — otherwise a capped site would
        keep consuming the org's headroom on every rejected call.

        If the site passes but the org is exhausted, the site charge is
        refunded, so a rejected call leaves both counters exactly as it found
        them. Counters expire at the end of the UTC day.
        """
        today = dt.datetime.now(dt.timezone.utc).date()

        site_charged = False
        if site_id is not None and self.site_cap is not None:
            if not await self._charge(self._site_key(site_id, today), cost_usd, self.site_cap):
                return False
            site_charged = True

        if not await self._charge(self._key(org_id, today), cost_usd, self.cap):
            if site_charged:
                await self.redis.incrbyfloat(self._site_key(site_id, today), -cost_usd)
            return False

        return True
