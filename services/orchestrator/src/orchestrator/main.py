from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shared.config import load_settings
from shared.logging import get_logger, setup_logging
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

settings = load_settings()
setup_logging(
    level=settings.logging.level,
    json_format=settings.logging.format == "json",
    redact_fields=settings.logging.redact_fields,
)
logger = get_logger("orchestrator")

redis_client: redis.Redis | None = None
_shutdown_event = asyncio.Event()


def parse_rate_limit(limit_str: str) -> str:
    return limit_str


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[parse_rate_limit(settings.rate_limiting.default)],
)


async def check_redis() -> bool:
    global redis_client
    try:
        if redis_client:
            await redis_client.ping()
            return True
        return False
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global redis_client
    logger.info("starting orchestrator", service="orchestrator")
    redis_client = redis.from_url(
        settings.redis.url, decode_responses=True, socket_connect_timeout=5
    )
    try:
        await redis_client.ping()
        logger.info("redis connected")
    except Exception as e:
        logger.warning("redis not available at startup", error=str(e))
        redis_client = None

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(handle_shutdown(s))
        )

    yield

    logger.info("shutting down orchestrator")
    if redis_client:
        await redis_client.aclose()
    logger.info("shutdown complete")
    sys.exit(0)


async def handle_shutdown(sig: signal.Signals) -> None:
    logger.info("received signal", signal=sig.name)
    _, pending = await asyncio.wait(
        [asyncio.sleep(settings.shutdown.grace_period_seconds)],
        timeout=settings.shutdown.grace_period_seconds,
    )
    if pending:
        logger.warning("graceful shutdown period expired, forcing exit")
    else:
        logger.info("shutdown complete")
    sys.exit(0)


app = FastAPI(title="J.A.R.V.I.S. Orchestrator", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return {"service": "orchestrator", "version": "0.1.0"}
