from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def ws_client():
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch("orchestrator.main.create_redis_clients", return_value=(None, None)),
        patch("orchestrator.main.create_llm_client"),
        patch("orchestrator.main.PromptManager"),
        patch("orchestrator.main.STTClient", return_value=AsyncMock()),
        patch("orchestrator.main.TTSClient", return_value=AsyncMock()),
        patch("orchestrator.main.MemoryClient", return_value=AsyncMock()),
        patch("orchestrator.main.ToolsClient", return_value=AsyncMock()),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = True
        mock_settings.auth.api_key = "test-secret-key"
        mock_settings.auth.api_key_header = "X-API-Key"

        from orchestrator.main import app

        with TestClient(app) as client:
            yield client


class TestWebSocketAuth:
    def test_ws_connect_with_valid_key(self, ws_client):
        with ws_client.websocket_connect(
            "/ws/audio", headers={"X-API-Key": "test-secret-key"}
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "session_id" in data

    def test_ws_connect_without_key_returns_denied(self, ws_client):
        with ws_client.websocket_connect("/ws/audio") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001

    def test_ws_connect_with_wrong_key_returns_denied(self, ws_client):
        with ws_client.websocket_connect(
            "/ws/audio", headers={"X-API-Key": "wrong-key"}
        ) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001

    def test_ws_auth_disabled_allows_all(self, ws_client):
        ws_client.app.state.settings.auth.enabled = False

        with ws_client.websocket_connect("/ws/audio") as ws:
            data = ws.receive_json()
            assert data["type"] == "connected"
