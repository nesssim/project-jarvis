from __future__ import annotations

from typing import Any

import httpx
from shared.logging import get_logger

logger = get_logger("orchestrator.clients.tools")


class ToolsClientError(Exception):
    pass


class ToolsClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        api_key: str | None = None,
        api_key_header: str = "X-API-Key",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self.api_key_header = api_key_header
        self._http: httpx.AsyncClient | None = None

    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {self.api_key_header: self.api_key}
        return {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._http

    async def list_tools(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get("/api/tools/list", headers=self._auth_headers())
        if resp.status_code >= 400:
            raise ToolsClientError(f"list_tools failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return data.get("tools", [])

    async def execute(self, tool: str, params: dict[str, Any] | None = None) -> Any:
        client = await self._get_client()
        resp = await client.post(
            "/api/tools/execute",
            json={"tool": tool, "params": params or {}},
            headers=self._auth_headers(),
        )
        if resp.status_code >= 400:
            raise ToolsClientError(f"execute failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return data.get("result")

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
