import redis.asyncio as redis

from app.config import settings

_redis_pool: redis.ConnectionPool | None = None


def _get_pool() -> redis.ConnectionPool:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_pool


async def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())
