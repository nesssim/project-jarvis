from __future__ import annotations

from typing import Any

import httpx
from shared.logging import get_logger

logger = get_logger("orchestrator.clients.memory")


class MemoryClientError(Exception):
    pass


class MemoryClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            )
        return self._http

    async def store_turn(
        self, session_id: str, role: str, content: str
    ) -> str:
        client = await self._get_client()
        resp = await client.post(
            "/api/memory/turns",
            json={
                "session_id": session_id,
                "role": role,
                "content": content,
            },
        )
        if resp.status_code >= 400:
            raise MemoryClientError(
                f"store_turn failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        return data.get("turn_id", "")

    async def get_recent(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(
            f"/api/memory/turns/{session_id}",
            params={"limit": limit},
        )
        if resp.status_code >= 400:
            raise MemoryClientError(
                f"get_recent failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        return data.get("turns", [])

    async def recall(
        self, session_id: str, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.post(
            "/api/memory/recall",
            json={
                "session_id": session_id,
                "query": query,
                "max_results": max_results,
            },
        )
        if resp.status_code >= 400:
            raise MemoryClientError(
                f"recall failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        return data.get("memories", [])

    async def clear_session(self, session_id: str) -> None:
        client = await self._get_client()
        resp = await client.delete(f"/api/memory/turns/{session_id}")
        if resp.status_code >= 400:
            raise MemoryClientError(
                f"clear_session failed: {resp.status_code} {resp.text}"
            )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
