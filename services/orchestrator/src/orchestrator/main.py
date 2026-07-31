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

from orchestrator.clients.llm import BaseLLMClient, create_llm_client
from orchestrator.clients.memory import MemoryClient
from orchestrator.clients.stt_client import STTClient
from orchestrator.clients.tools import ToolsClient
from orchestrator.clients.tts_client import TTSClient
from orchestrator.core.prompt import PromptManager
from orchestrator.routes.chat import router as chat_router
from orchestrator.routes.voice import router as voice_router
from orchestrator.routes.ws import router as ws_router

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


async def _warmup_llm(llm_client: BaseLLMClient) -> None:
    """Pre-warm the LLM connection by sending a minimal request."""
    try:
        async for _ in llm_client.generate(
            messages=[{"role": "user", "content": "Hello"}], stream=True
        ):
            break
        logger.info("llm warmup complete")
    except Exception as e:
        logger.warning("llm warmup failed (non-fatal)", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global redis_client, redis_binary
    logger.info("starting orchestrator", service="orchestrator")
    redis_client, redis_binary = await create_redis_clients(settings)

    app.state.settings = settings
    app.state.llm_client = create_llm_client(settings.llm)
    app.state.warmup_task = asyncio.create_task(_warmup_llm(app.state.llm_client))
    app.state.prompt_manager = PromptManager()
    app.state.stt_client = STTClient(
        settings.internal_urls.stt,
        api_key=settings.auth.api_key if settings.auth.enabled else None,
        api_key_header=settings.auth.api_key_header,
    )
    app.state.tts_client = TTSClient(
        settings.internal_urls.tts,
        api_key=settings.auth.api_key if settings.auth.enabled else None,
        api_key_header=settings.auth.api_key_header,
    )
    app.state.memory_client = MemoryClient(
        settings.internal_urls.memory,
        api_key=settings.auth.api_key if settings.auth.enabled else None,
        api_key_header=settings.auth.api_key_header,
    )
    app.state.tools_client = ToolsClient(
        settings.internal_urls.tools,
        api_key=settings.auth.api_key if settings.auth.enabled else None,
        api_key_header=settings.auth.api_key_header,
    )

    if threading.current_thread() is threading.main_thread():
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):

            def _sig_handler(s: signal.Signals = sig) -> None:
                asyncio.create_task(handle_shutdown(s))  # noqa: RUF006

            loop.add_signal_handler(sig, _sig_handler)

    yield

    logger.info("shutting down orchestrator")
    warmup_task = getattr(app.state, "warmup_task", None)
    if warmup_task is not None and not warmup_task.done():
        warmup_task.cancel()
    await close_redis_clients(redis_client, redis_binary)
    for attr in ("stt_client", "tts_client", "memory_client", "tools_client"):
        client = getattr(app.state, attr, None)
        if client is not None:
            close_method = getattr(client, "close", None)
            if callable(close_method):
                try:
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as e:
                    logger.debug("close failed", error=str(e))
    _shutdown_event.set()
    logger.info("shutdown complete")


async def handle_shutdown(sig: signal.Signals) -> None:
    logger.info("received signal", signal=sig.name)
    await asyncio.sleep(settings.shutdown.grace_period_seconds)
    _shutdown_event.set()


app = FastAPI(title="J.A.R.V.I.S. Orchestrator", version="0.1.0", lifespan=lifespan)


app.include_router(chat_router)
app.include_router(voice_router)
app.include_router(ws_router)

setup_cors(app, settings)


add_request_size_limit(app)
setup_auth(app, settings)
setup_rate_limiter(app, limiter)


@app.get("/health")
@limiter.exempt
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
