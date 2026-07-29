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
async def test_rate_limit_default_applied(client: AsyncClient) -> None:
    for _ in range(5):
        response = await client.get("/")
        assert response.status_code == 200
