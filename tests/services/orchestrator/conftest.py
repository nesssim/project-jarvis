from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class MockLLM:
    tokens: list[str]

    def __init__(self, tokens: list[str] | None = None):
        self.tokens = tokens or ["mock ", "response"]
        self.captured_kwargs: dict | None = None

    async def generate(self, messages, _stream=True, _max_tokens=None, _temperature=None):
        self.captured_kwargs = {"messages": messages}
        for t in self.tokens:
            yield t


class MockPromptManager:
    def __init__(self, body: str = "You are a helpful test assistant."):
        self.body = body

    def render(self, **_kwargs) -> str:
        return self.body


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def mock_prompt_manager():
    return MockPromptManager()


@pytest.fixture
def test_client(mock_llm, mock_prompt_manager):
    with (
        patch("services.orchestrator.src.orchestrator.main.settings") as mock_settings,
        patch(
            "services.orchestrator.src.orchestrator.main.create_redis_clients",
            return_value=(None, None),
        ),
        patch(
            "services.orchestrator.src.orchestrator.main.create_llm_client",
            return_value=mock_llm,
        ),
        patch(
            "services.orchestrator.src.orchestrator.main.PromptManager",
            return_value=mock_prompt_manager,
        ),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        from services.orchestrator.src.orchestrator.main import app

        with TestClient(app) as client:
            yield client
