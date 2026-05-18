import asyncio
import logging

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None

# When Docker starts all services at once, Redis may not be ready for a few
# seconds after the server process boots. This retry loop prevents a hard
# crash at startup when that race condition happens.
_REDIS_STARTUP_RETRIES = 10
_REDIS_RETRY_BACKOFF = 2  # seconds between attempts


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        logger.info("Connecting to Redis at %s…", settings.REDIS_URL)
        for attempt in range(1, _REDIS_STARTUP_RETRIES + 1):
            try:
                client = aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await client.ping()
                _redis_client = client
                logger.info("Redis connection established.")
                break
            except Exception as exc:
                if attempt == _REDIS_STARTUP_RETRIES:
                    raise RuntimeError(
                        f"Could not connect to Redis after {_REDIS_STARTUP_RETRIES} attempts."
                    ) from exc
                logger.warning(
                    "Redis not ready (attempt %d/%d): %s — retrying in %ds…",
                    attempt, _REDIS_STARTUP_RETRIES, exc, _REDIS_RETRY_BACKOFF,
                )
                await asyncio.sleep(_REDIS_RETRY_BACKOFF)
    return _redis_client


def get_redis_client() -> aioredis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis not initialised — call get_redis() first.")
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        logger.info("Redis connection closed.")
