from __future__ import annotations

import json
from io import StringIO

import structlog
from shared.logging import get_logger


def test_logger_creates() -> None:
    logger = get_logger("test")
    assert logger is not None


def test_json_output() -> None:
    buf = StringIO()
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(buf),
        cache_logger_on_first_use=True,
    )
    logger = get_logger("test_json")
    logger.info("test message", extra_field="value")
    output = buf.getvalue()
    parsed = json.loads(output.strip())
    assert parsed["event"] == "test message"
    assert parsed["extra_field"] == "value"
    assert "timestamp" in parsed


def test_get_logger_reuses_config() -> None:
    logger1 = get_logger("module_a")
    logger2 = get_logger("module_b")
    assert logger1 is not None
    assert logger2 is not None
