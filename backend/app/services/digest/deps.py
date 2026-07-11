import logging

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.service import DigestService
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import notification_service

logger = logging.getLogger(__name__)


class _StubGeminiClient:
    """Fallback when google-genai is unavailable or no API key configured.

    Attempting to call .aio.models.generate_content raises a clear runtime error,
    which DigestService catches and converts to a degraded digest.
    """

    class _Models:
        async def generate_content(self, *args, **kwargs):
            raise RuntimeError(
                "Gemini client unavailable: GEMINI_API_KEY not set "
                "or google-genai package not installed"
            )

    class _Aio:
        models = None

        def __init__(self):
            self.models = _StubGeminiClient._Models()

    aio = None

    def __init__(self):
        self.aio = _StubGeminiClient._Aio()


def _gemini_client():
    """Build a Gemini client lazily so missing creds/package don't break imports."""
    if not settings.gemini_api_key:
        return _StubGeminiClient()
    try:
        from google import genai  # type: ignore
    except ImportError:
        logger.warning("google-genai package not installed; using stub Gemini client")
        return _StubGeminiClient()
    return genai.Client(api_key=settings.gemini_api_key)


async def _redis_dep():
    return await get_redis()


async def get_digest_service(
    db: AsyncSession = Depends(get_db),
    redis=Depends(_redis_dep),
) -> DigestService:
    gemini = GeminiDigestClient(genai_client=_gemini_client())
    spend = SpendTracker(redis_client=redis, daily_cap_usd=settings.digest_daily_spend_cap_usd)
    return DigestService(
        db=db,
        gemini=gemini,
        spend_tracker=spend,
        notification=notification_service,
        dashboard_base_url=settings.dashboard_base_url,
    )
