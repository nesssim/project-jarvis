from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tools.registry import ToolRegistry


async def _mock_search(query: str, max_results: int = 5) -> dict:
    return {
        "results": [{"title": "Mock", "url": "https://mock.com", "snippet": "mock"}]
    }


async def _mock_any(**kwargs: object) -> dict:
    return {"ok": True, **kwargs}


@pytest.fixture
def test_client():
    with (
        patch("tools.main.create_redis_clients", return_value=(None, None)),
        patch("tools.main.settings") as mock_settings,
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = False
        mock_settings.tools.safety_tiers = {
            "safe": ["web_search"],
            "confirm": [],
            "restricted": [],
        }
        mock_settings.tools.safety_permitted_tier = "safe"
        from tools.main import app

        app.state.tool_registry = ToolRegistry()
        app.state.tool_registry.register("web_search", "Search the web", _mock_search)
        with TestClient(app) as client:
            yield client


class TestToolsRoutes:
    def test_list_tools(self, test_client):
        resp = test_client.get("/api/tools/list")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        names = [t["name"] for t in data["tools"]]
        assert "web_search" in names

    def test_execute_tool(self, test_client):
        resp = test_client.post(
            "/api/tools/execute",
            json={"tool": "web_search", "params": {"query": "test"}},
        )
        assert resp.status_code == 200
        assert "result" in resp.json()

    def test_execute_not_found(self, test_client):
        resp = test_client.post(
            "/api/tools/execute", json={"tool": "nonexistent", "params": {}}
        )
        assert resp.status_code == 404

    def test_execute_restricted_tool_denied(self, test_client):
        test_client.app.state.tool_registry.register(
            "execute_command", "Run a command", _mock_search
        )
        resp = test_client.post(
            "/api/tools/execute", json={"tool": "execute_command", "params": {}}
        )
        assert resp.status_code == 403
        assert "safety tier" in resp.json()["error"]

    def test_execute_confirm_tool_allowed_when_permitted(self, test_client):
        test_client.app.state.settings.tools.safety_tiers["confirm"] = ["write_file"]
        test_client.app.state.settings.tools.safety_permitted_tier = "confirm"
        test_client.app.state.tool_registry.register(
            "write_file", "Write a file", _mock_any
        )
        resp = test_client.post(
            "/api/tools/execute",
            json={"tool": "write_file", "params": {"path": "/data/sandbox/test.txt"}},
        )
        assert resp.status_code == 200

    def test_execute_validation(self, test_client):
        resp = test_client.post("/api/tools/execute", json={"tool": "", "params": {}})
        assert resp.status_code == 422

    def test_search_endpoint(self, test_client):
        with patch("tools.search.web_search") as mock_search:
            mock_search.return_value = {"results": []}
            resp = test_client.post(
                "/api/tools/search", json={"query": "test", "max_results": 3}
            )
        assert resp.status_code == 200

    def test_search_validation(self, test_client):
        resp = test_client.post("/api/tools/search", json={"query": ""})
        assert resp.status_code == 422

    def test_health(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code in (200, 503)
