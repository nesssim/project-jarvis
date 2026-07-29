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
from shared.http import setup_cors
from shared.logging import get_logger, setup_logging
from shared.redis import close_redis_clients, create_redis_clients
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from orchestrator.clients.llm import create_llm_client
from orchestrator.core.prompt import PromptManager
from orchestrator.routes.chat import router as chat_router

settings = load_settings()
setup_logging(
    level=settings.logging.level,
    json_format=settings.logging.format == "json",
    redact_fields=settings.logging.redact_fields,
)
logger = get_logger("orchestrator")

redis_client: redis.Redis | None = None
redis_binary: redis.Redis | None = None
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
    global redis_client, redis_binary
    logger.info("starting orchestrator", service="orchestrator")
    redis_client, redis_binary = await create_redis_clients(settings)

    app.state.llm_client = create_llm_client(settings.llm)
    app.state.prompt_manager = PromptManager()

    if threading.current_thread() is threading.main_thread():
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):

            def _sig_handler(s: signal.Signals = sig) -> None:
                asyncio.create_task(handle_shutdown(s))  # noqa: RUF006

            loop.add_signal_handler(sig, _sig_handler)

    yield

    logger.info("shutting down orchestrator")
    await close_redis_clients(redis_client, redis_binary)
    _shutdown_event.set()
    logger.info("shutdown complete")


async def handle_shutdown(sig: signal.Signals) -> None:
    logger.info("received signal", signal=sig.name)
    await asyncio.sleep(settings.shutdown.grace_period_seconds)
    _shutdown_event.set()


app = FastAPI(title="J.A.R.V.I.S. Orchestrator", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

app.include_router(chat_router)

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
    return {"service": "orchestrator", "version": "0.1.0"}
