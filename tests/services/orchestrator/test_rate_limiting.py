from __future__ import annotations

from fastapi.testclient import TestClient


def test_rate_limit_default_applied(test_client: TestClient) -> None:
    for _ in range(5):
        response = test_client.get("/")
        assert response.status_code == 200
