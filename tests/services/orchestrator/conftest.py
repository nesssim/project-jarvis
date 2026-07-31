from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


class MockLLM:
    tokens: list[str]

    def __init__(self, tokens: list[str] | None = None):
        self.tokens = tokens or ["mock ", "response"]
        self.captured_kwargs: dict | None = None
        self.config = type(
            "obj",
            (object,),
            {"generation": type("obj", (object,), {"max_tokens": 2048})},
        )()

    async def generate(
        self, messages, _stream=True, _max_tokens=None, _temperature=None
    ):
        self.captured_kwargs = {"messages": messages}
        for t in self.tokens:
            yield t


class MockPromptManager:
    def __init__(self, body: str = "You are a helpful test assistant."):
        self.body = body

    def render(self, **_kwargs) -> str:
        return self.body


class MockMemoryClient:
    def __init__(self):
        self.store_turn = AsyncMock(return_value="mock_turn_id")
        self.recall = AsyncMock(return_value=[])
        self.get_recent = AsyncMock(return_value=[])
        self.clear_session = AsyncMock()
        self.close = AsyncMock()

    async def store_turn(self, session_id, role, content):
        return "mock_turn_id"

    async def recall(self, session_id, query, max_results=5):
        return []

    async def get_recent(self, session_id, limit=20):
        return []

    async def clear_session(self, session_id):
        pass

    async def close(self):
        pass


class MockToolsClient:
    def __init__(self):
        self.execute = AsyncMock(return_value={"results": []})
        self.list_tools = AsyncMock(return_value=[])
        self.close = AsyncMock()

    async def execute(self, tool, params=None):
        return {"results": []}

    async def list_tools(self):
        return []

    async def close(self):
        pass


@pytest.fixture
def mock_memory_client():
    return MockMemoryClient()


@pytest.fixture
def mock_tools_client():
    return MockToolsClient()


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def mock_prompt_manager():
    return MockPromptManager()


@pytest.fixture
def test_client(mock_llm, mock_prompt_manager, mock_memory_client, mock_tools_client):
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch(
            "orchestrator.main.create_redis_clients",
            return_value=(None, None),
        ),
        patch(
            "orchestrator.main.create_llm_client",
            return_value=mock_llm,
        ),
        patch(
            "orchestrator.main.PromptManager",
            return_value=mock_prompt_manager,
        ),
        patch(
            "orchestrator.main.MemoryClient",
            return_value=mock_memory_client,
        ),
        patch(
            "orchestrator.main.ToolsClient",
            return_value=mock_tools_client,
        ),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = False
        from orchestrator.main import app

        with TestClient(app) as client:
            yield client
