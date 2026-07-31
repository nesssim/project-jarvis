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
from shared.http import (
    add_request_size_limit,
    setup_auth,
    setup_cors,
    setup_rate_limiter,
)
from shared.logging import get_logger, setup_logging
from shared.redis import close_redis_clients, create_redis_clients
from slowapi import Limiter
from slowapi.util import get_remote_address

from tools.registry import ToolRegistry
from tools.routes import router as tools_router

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
    logger.info("starting tools service")
    redis_client, redis_binary = await create_redis_clients(settings)
    app.state.settings = settings

    from tools.search import web_search

    app.state.tool_registry = ToolRegistry()
    app.state.tool_registry.register(
        name="web_search",
        description="Search the web for current information",
        handler=web_search,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )
    app.include_router(tools_router)

    if threading.current_thread() is threading.main_thread():
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


setup_cors(app, settings)
add_request_size_limit(app)
setup_auth(app, settings)
setup_rate_limiter(app, limiter)


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
