import logging

from fastapi import Depends

from app.config import settings
from app.core.redis import get_redis
from app.services.digest.deps import _gemini_client
from app.services.digest.spend_tracker import SpendTracker
from app.services.sequence_compiler.gemini_client import SequenceCompilerClient

logger = logging.getLogger(__name__)


async def _redis_dep():
    return await get_redis()


async def get_sequence_compiler_client() -> SequenceCompilerClient:
    # Reuses digest's lazy client builder (handles missing API key / package
    # via a stub that raises clearly) rather than duplicating that logic.
    return SequenceCompilerClient(genai_client=_gemini_client())


async def get_sequence_compiler_spend_tracker(redis=Depends(_redis_dep)) -> SpendTracker:
    # Deliberately shares the digest spend cap/key namespace (digest:spend:{org_id}:{day},
    # digest_daily_spend_cap_usd) rather than a separate budget — an explicit product
    # decision, not an oversight (see the design doc's spend-cap tradeoff section).
    return SpendTracker(
        redis_client=redis,
        daily_cap_usd=settings.digest_daily_spend_cap_usd,
        site_daily_cap_usd=settings.digest_site_daily_spend_cap_usd or None,
    )
