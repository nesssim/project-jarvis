from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    with (
        patch("memory.main.create_redis_clients", return_value=(None, None)),
        patch("memory.main.settings") as mock_settings,
    ):
        mock_settings.memory.short_term.max_turns = 20
        mock_settings.rate_limiting.default = "100/minute"
        from memory.main import app

        with TestClient(app) as client:
            yield client


class TestMemoryRoutes:
    def test_store_turn(self, test_client):
        mock_store = AsyncMock()
        mock_store.store_turn = AsyncMock(return_value="abc123def4567890")
        mock_store.get_recent = AsyncMock(return_value=[])
        mock_store.recall = AsyncMock(return_value=[])
        test_client.app.state.memory_store = mock_store

        resp = test_client.post(
            "/api/memory/turns",
            json={"session_id": "s1", "role": "user", "content": "hello"},
        )
        assert resp.status_code == 201
        assert resp.json()["turn_id"] == "abc123def4567890"

    def test_store_validation_empty_message(self, test_client):
        resp = test_client.post(
            "/api/memory/turns",
            json={"session_id": "s1", "role": "user", "content": ""},
        )
        assert resp.status_code == 422

    def test_store_validation_bad_role(self, test_client):
        resp = test_client.post(
            "/api/memory/turns",
            json={"session_id": "s1", "role": "admin", "content": "hello"},
        )
        assert resp.status_code == 422

    def test_get_recent_empty(self, test_client):
        mock_store = AsyncMock()
        mock_store.get_recent = AsyncMock(return_value=[])
        test_client.app.state.memory_store = mock_store

        resp = test_client.get("/api/memory/turns/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["turns"] == []

    def test_get_recent_after_store(self, test_client):
        mock_store = AsyncMock()
        mock_store.get_recent = AsyncMock(
            return_value=[
                {"turn_id": "1", "role": "user", "content": "first", "timestamp": 1.0},
                {
                    "turn_id": "2",
                    "role": "assistant",
                    "content": "response",
                    "timestamp": 2.0,
                },
            ]
        )
        test_client.app.state.memory_store = mock_store

        resp = test_client.get("/api/memory/turns/s1")
        assert len(resp.json()["turns"]) == 2

    def test_recall(self, test_client):
        mock_store = AsyncMock()
        mock_store.recall = AsyncMock(
            return_value=[{"content": "Python", "score": 0.8}]
        )
        test_client.app.state.memory_store = mock_store

        resp = test_client.post(
            "/api/memory/recall",
            json={"session_id": "s1", "query": "Python", "max_results": 5},
        )
        assert len(resp.json()["memories"]) >= 1

    def test_recall_validation(self, test_client):
        resp = test_client.post(
            "/api/memory/recall", json={"session_id": "s1", "query": ""}
        )
        assert resp.status_code == 422

    def test_clear_session(self, test_client):
        mock_store = AsyncMock()
        mock_store.clear_session = AsyncMock()
        test_client.app.state.memory_store = mock_store

        resp = test_client.delete("/api/memory/turns/s1")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_health(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code in (200, 503)
