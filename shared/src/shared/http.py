from __future__ import annotations

from collections.abc import Callable
from hmac import compare_digest

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

_AUTH_FREE_PATHS = ("/health", "/", "/docs", "/redoc", "/openapi.json")


def _normalized_path(request: Request) -> str:
    return request.url.path.rstrip("/") or "/"


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


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, get_settings: Callable[[], Settings]) -> None:
        super().__init__(app)
        self.get_settings = get_settings

    async def dispatch(self, request: Request, call_next):
        if (
            request.method == "OPTIONS"
            and "access-control-request-method" in request.headers
        ):
            return await call_next(request)
        settings = self.get_settings()
        if settings.auth.enabled and _normalized_path(request) not in _AUTH_FREE_PATHS:
            expected = settings.auth.api_key
            provided = request.headers.get(settings.auth.api_key_header, "")
            if not expected or not compare_digest(provided, expected):
                logger.warning("auth rejected", path=request.url.path)
                return JSONResponse(
                    status_code=401, content={"detail": "Invalid or missing API key"}
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


def setup_auth(app: FastAPI, settings: Settings) -> None:
    if not settings.auth.enabled:
        logger.warning(
            "Service auth is DISABLED — endpoints accept requests without an API key"
        )
    app.add_middleware(AuthMiddleware, get_settings=lambda: settings)


def setup_rate_limiter(
    app: FastAPI,
    limiter: Limiter,
    middleware_cls: type[SlowAPIMiddleware] | None = None,
) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
    cls = middleware_cls or SafeSlowAPIMiddleware
    app.add_middleware(cls)
