import asyncio
import logging
import redis.asyncio as aioredis
from .config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        for attempt in range(10):
            try:
                _redis = aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await _redis.ping()
                logger.info("Redis client connected.")
                return _redis
            except Exception as exc:
                logger.warning(f"Redis not ready (attempt {attempt + 1}/10): {exc}")
                await asyncio.sleep(2)
        raise RuntimeError("Could not connect to Redis after 10 attempts.")
    return _redis
