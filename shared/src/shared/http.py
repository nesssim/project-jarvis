from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import (
    SlowAPIMiddleware,
    _find_route_handler,
    _should_exempt,
    sync_check_limits,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from shared.config import Settings
from shared.logging import get_logger

logger = get_logger("shared.http")

MAX_BODY_SIZE = 50 * 1024 * 1024  # 50MB


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    return _rate_limit_exceeded_handler(request, exc)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413, content={"detail": "Request body too large"}
            )
        return await call_next(request)


class SafeSlowAPIMiddleware(SlowAPIMiddleware):
    async def dispatch(self, request, call_next):
        app = request.app
        limiter = app.state.limiter

        if not limiter.enabled:
            return await call_next(request)

        handler = _find_route_handler(app.routes, request.scope)
        if _should_exempt(limiter, handler):
            return await call_next(request)

        error_response, should_inject_headers = sync_check_limits(
            limiter, request, handler, app
        )
        if error_response is not None:
            return error_response

        response = await call_next(request)
        if should_inject_headers and hasattr(request.state, "view_rate_limit"):
            response = limiter._inject_headers(  # noqa: SLF001
                response, request.state.view_rate_limit
            )
        return response


def setup_cors(app: FastAPI, settings: Settings) -> None:
    origins = settings.cors.allowed_origins
    allow_credentials = settings.cors.allow_credentials
    if not origins or origins == ["*"]:
        logger.warning("CORS configured with wildcard origins")
        if allow_credentials:
            logger.error(
                "Cannot use allow_credentials=True with wildcard origins — forcing allow_credentials=False"
            )
            allow_credentials = False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
    )


def add_request_size_limit(app: FastAPI) -> None:
    app.add_middleware(RequestSizeLimitMiddleware)


def setup_rate_limiter(
    app: FastAPI,
    limiter: Limiter,
    middleware_cls: type[SlowAPIMiddleware] | None = None,
) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
    cls = middleware_cls or SafeSlowAPIMiddleware
    app.add_middleware(cls)
