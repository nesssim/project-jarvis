from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from shared.config import load_settings
from shared.http import add_request_size_limit, setup_cors, setup_rate_limiter
from shared.logging import get_logger, setup_logging
from shared.redis import close_redis_clients, create_redis_clients
from slowapi import Limiter
from slowapi.util import get_remote_address

from stt.routes.transcribe import router as transcribe_router
from stt.routes.transcribe_stream import router as transcribe_stream_router
from stt.routes.vad_check import router as vad_router

settings = load_settings()
setup_logging(
    level=settings.logging.level, json_format=settings.logging.format == "json"
)
logger = get_logger("stt")

redis_client: redis.Redis | None = None
redis_binary: redis.Redis | None = None
_shutdown_event = asyncio.Event()

limiter = Limiter(
    key_func=get_remote_address, default_limits=[settings.rate_limiting.default]
)


async def check_redis() -> bool:
    global redis_client
    if redis_client is None:
        return True
    try:
        await redis_client.ping()
        return True
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global redis_client, redis_binary
    logger.info("starting stt service")
    redis_client, redis_binary = await create_redis_clients(settings)

    if threading.current_thread() is threading.main_thread():
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):

            def _sig_handler(s: signal.Signals = sig) -> None:
                asyncio.create_task(handle_shutdown(s))  # noqa: RUF006

            loop.add_signal_handler(sig, _sig_handler)

    yield

    logger.info("shutting down stt service")
    await close_redis_clients(redis_client, redis_binary)
    _shutdown_event.set()


async def handle_shutdown(sig: signal.Signals) -> None:
    logger.info("received signal", signal=sig.name)
    await asyncio.sleep(settings.shutdown.grace_period_seconds)
    _shutdown_event.set()


app = FastAPI(title="J.A.R.V.I.S. STT", version="0.1.0", lifespan=lifespan)
setup_rate_limiter(app, limiter)

app.include_router(transcribe_router)
app.include_router(transcribe_stream_router)
app.include_router(vad_router)

setup_cors(app, settings)
add_request_size_limit(app)


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
    return {"service": "stt", "version": "0.1.0"}
