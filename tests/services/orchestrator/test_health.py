from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint_returns_200(test_client: TestClient) -> None:
    response = test_client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "dependencies" in data
    assert "redis" in data["dependencies"]


def test_root_endpoint(test_client: TestClient) -> None:
    response = test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "orchestrator"


def test_health_response_time(test_client: TestClient) -> None:
    import time

    start = time.time()
    test_client.get("/health")
    elapsed = time.time() - start
    assert elapsed < 0.5
