from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import Settings
from shared.logging import get_logger

logger = get_logger("shared.http")


def setup_cors(app: FastAPI, settings: Settings) -> None:
    origins = settings.cors.allowed_origins
    if not origins or origins == ["*"]:
        logger.warning("CORS configured with wildcard origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
    )
