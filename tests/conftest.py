from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import BaseModel
from shared.config import Settings
from shared.logging import setup_logging

TEST_DIR = Path(__file__).parent
FIXTURES_DIR = TEST_DIR / "fixtures"


class HealthResponse(BaseModel):
    status: str
    dependencies: dict[str, bool]


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def configure_logging() -> None:
    setup_logging(level="DEBUG", json_format=False)


@pytest.fixture
def mock_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        redis={"url": "redis://:test@localhost:6379/0"},
        logging={"level": "DEBUG", "format": "text"},
    )


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient() as client:
        yield client


def load_fixture(name: str) -> dict[str, Any]:
    import json

    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open() as f:
        return json.load(f)
