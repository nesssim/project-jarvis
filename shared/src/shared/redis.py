from __future__ import annotations

import redis.asyncio as redis

from shared.config import Settings
from shared.logging import get_logger

logger = get_logger("shared.redis")


async def create_redis_clients(
    settings: Settings,
) -> tuple[redis.Redis | None, redis.Redis | None]:
    redis_client: redis.Redis | None = None
    redis_binary: redis.Redis | None = None

    try:
        redis_client = redis.from_url(
            settings.redis.url, decode_responses=True, socket_connect_timeout=5
        )
        await redis_client.ping()
        logger.info("redis connected")
    except Exception as e:
        logger.warning("redis not available at startup", error=str(e))
        redis_client = None

    try:
        redis_binary = redis.from_url(
            settings.redis.url, decode_responses=False, socket_connect_timeout=5
        )
        await redis_binary.ping()
        logger.info("redis binary client connected")
    except Exception as e:
        logger.warning("redis binary client not available", error=str(e))
        redis_binary = None

    return redis_client, redis_binary


async def close_redis_clients(
    redis_client: redis.Redis | None, redis_binary: redis.Redis | None
) -> None:
    if redis_client:
        await redis_client.aclose()
    if redis_binary:
        await redis_binary.aclose()
