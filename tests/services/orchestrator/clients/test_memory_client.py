from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from orchestrator.clients.memory import MemoryClient, MemoryClientError


def _mock_resp(status_code: int, json_data: dict):
    """Build a synchronous mock httpx Response."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data
    return m


@pytest.fixture
def client():
    return MemoryClient("http://memory:8003", timeout=5.0)


class TestMemoryClient:
    async def test_store_turn(self, client):
        mock_resp = _mock_resp(201, {"turn_id": "abc123"})

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            turn_id = await client.store_turn("s1", "user", "hello")
            assert turn_id == "abc123"
            mock_http.post.assert_called_once()

    async def test_store_turn_failure(self, client):
        mock_resp = _mock_resp(500, {})
        mock_resp.text = "Internal error"

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            with pytest.raises(MemoryClientError):
                await client.store_turn("s1", "user", "hello")

    async def test_get_recent(self, client):
        mock_resp = _mock_resp(200, {"turns": [{"turn_id": "t1", "role": "user"}]})

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            turns = await client.get_recent("s1", limit=10)
            assert len(turns) == 1
            assert turns[0]["turn_id"] == "t1"

    async def test_recall(self, client):
        mock_resp = _mock_resp(200, {"memories": [{"content": "test", "score": 0.5}]})

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            memories = await client.recall("s1", "test query")
            assert len(memories) == 1

    async def test_close(self, client):
        mock_http = MagicMock()
        mock_http.aclose = AsyncMock()
        client._http = mock_http
        await client.close()
        mock_http.aclose.assert_called_once()
        assert client._http is None

    async def test_close_noop(self, client):
        await client.close()
