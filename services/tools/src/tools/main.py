from __future__ import annotations

import asyncio
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from shared.config import load_settings
from shared.http import setup_cors
from shared.logging import get_logger, setup_logging
from shared.redis import close_redis_clients, create_redis_clients
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

settings = load_settings()
setup_logging(
    level=settings.logging.level, json_format=settings.logging.format == "json"
)
logger = get_logger("tools")

redis_client: redis.Redis | None = None
redis_binary: redis.Redis | None = None
_shutdown_event = asyncio.Event()

limiter = Limiter(
    key_func=get_remote_address, default_limits=[settings.rate_limiting.default]
)


async def check_redis() -> bool:
    try:
        if redis_client:
            await redis_client.ping()
            return True
        return False
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global redis_client, redis_binary
    logger.info("starting tools service")
    redis_client, redis_binary = await create_redis_clients(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):

        def _sig_handler(s: signal.Signals = sig) -> None:
            asyncio.create_task(handle_shutdown(s))  # noqa: RUF006

        loop.add_signal_handler(sig, _sig_handler)

    yield

    logger.info("shutting down tools service")
    await close_redis_clients(redis_client, redis_binary)
    _shutdown_event.set()


async def handle_shutdown(sig: signal.Signals) -> None:
    logger.info("received signal", signal=sig.name)
    await asyncio.sleep(settings.shutdown.grace_period_seconds)
    _shutdown_event.set()


app = FastAPI(title="J.A.R.V.I.S. Tools", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

setup_cors(app, settings)


@app.get("/health")
async def health():
    redis_ok = await check_redis()
    status = "ok" if redis_ok else "degraded"
    return JSONResponse(
        content={"status": status, "dependencies": {"redis": redis_ok}},
        status_code=200 if redis_ok else 503,
    )


@app.get("/")
async def root():
    return {"service": "tools", "version": "0.1.0"}
