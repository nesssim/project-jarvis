from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services.orchestrator.src.orchestrator.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "dependencies" in data
    assert "redis" in data["dependencies"]


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "orchestrator"


@pytest.mark.asyncio
async def test_health_response_time(client: AsyncClient) -> None:
    import time

    start = time.time()
    await client.get("/health")
    elapsed = time.time() - start
    assert elapsed < 0.5
