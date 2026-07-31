from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from shared.config import Settings
from shared.http import AuthMiddleware


def _make_client(**auth: object) -> TestClient:
    settings = Settings(
        auth={"enabled": True, "api_key": "s3cret-key", "api_key_header": "X-API-Key"}
        | auth
    )

    app = FastAPI()
    app.add_middleware(AuthMiddleware, get_settings=lambda: settings)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> dict:
        return {"service": "test"}

    @app.get("/protected")
    async def protected() -> dict:
        return {"ok": True}

    return TestClient(app)


class TestAuthMiddleware:
    def test_protected_without_key_rejected(self) -> None:
        client = _make_client()
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_protected_with_wrong_key_rejected(self) -> None:
        client = _make_client()
        resp = client.get("/protected", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_protected_with_valid_key_allowed(self) -> None:
        client = _make_client()
        resp = client.get("/protected", headers={"X-API-Key": "s3cret-key"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_health_is_free_path(self) -> None:
        client = _make_client()
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_root_is_free_path(self) -> None:
        client = _make_client()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_custom_header_name(self) -> None:
        client = _make_client(api_key_header="Authorization")
        resp = client.get("/protected", headers={"Authorization": "Bearer s3cret-key"})
        assert resp.status_code == 401

        resp = client.get("/protected", headers={"Authorization": "s3cret-key"})
        assert resp.status_code == 200

    def test_disabled_auth_allows_requests(self) -> None:
        settings = Settings(
            auth={"enabled": False, "api_key": "", "api_key_header": "X-API-Key"}
        )
        app = FastAPI()
        app.add_middleware(AuthMiddleware, get_settings=lambda: settings)

        @app.get("/anything")
        async def anything() -> dict:
            return {"ok": True}

        with TestClient(app) as client:
            resp = client.get("/anything")
            assert resp.status_code == 200
