from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import AsyncClient
from shared.config import Settings
from shared.logging import setup_logging

os.environ.setdefault("AUTH__ENABLED", "false")
os.environ.setdefault("AUTH__API_KEY", "test-api-key")


def make_audio_chunk(duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Generate a synthetic audio chunk (440Hz sine wave) for testing."""
    import math

    num_samples = sample_rate * duration_ms // 1000
    samples = bytearray()
    for i in range(num_samples):
        val = int(math.sin(2 * math.pi * 440 * i / sample_rate) * 8000)
        samples.extend(val.to_bytes(2, "little", signed=True))
    return bytes(samples)


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
