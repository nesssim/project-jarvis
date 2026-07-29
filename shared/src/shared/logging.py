from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
import structlog.types

_REDACTED = "***"


def redact_sensitive_fields(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    sensitive_keys = {"api_key", "password", "token", "secret", "authorization"}
    for key in list(event_dict.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            event_dict[key] = _REDACTED
    return event_dict


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    redact_fields: list[str] | None = None,
) -> None:
    processors: list[structlog.types.Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if redact_fields:

        def redact_processor(
            logger: structlog.types.WrappedLogger,
            method_name: str,
            event_dict: MutableMapping[str, Any],
        ) -> MutableMapping[str, Any]:
            for field in redact_fields:
                if field in event_dict:
                    event_dict[field] = _REDACTED
            return event_dict

        processors.append(redact_processor)

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
