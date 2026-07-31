from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from orchestrator.clients.tools import ToolsClient, ToolsClientError


def _mock_resp(status_code: int, json_data: dict):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data
    return m


@pytest.fixture
def client():
    return ToolsClient("http://tools:8004", timeout=5.0)


class TestToolsClient:
    async def test_list_tools(self, client):
        mock_resp = _mock_resp(200, {"tools": [{"name": "web_search"}]})

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            tools = await client.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "web_search"

    async def test_execute(self, client):
        mock_resp = _mock_resp(200, {"result": {"results": []}})

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await client.execute("web_search", {"query": "test"})
            assert "results" in result

    async def test_execute_failure(self, client):
        mock_resp = _mock_resp(500, {})
        mock_resp.text = "error"

        with patch.object(client, "_get_client") as mock_get:
            mock_http = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            with pytest.raises(ToolsClientError):
                await client.execute("web_search", {"query": "test"})

    async def test_close(self, client):
        mock_http = MagicMock()
        mock_http.aclose = AsyncMock()
        client._http = mock_http
        await client.close()
        mock_http.aclose.assert_called_once()

    async def test_close_noop(self, client):
        await client.close()
