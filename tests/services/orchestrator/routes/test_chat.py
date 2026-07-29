from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Build a TestClient with mocked LLM client and prompt manager."""
    llm = MockLLM()
    pm = MagicMock()
    pm.render = MagicMock(return_value="You are a helpful assistant.")
    with (
        patch("services.orchestrator.src.orchestrator.main.settings") as mock_settings,
        patch(
            "services.orchestrator.src.orchestrator.main.create_redis_clients",
            return_value=(None, None),
        ),
        patch(
            "services.orchestrator.src.orchestrator.main.create_llm_client",
            return_value=llm,
        ),
        patch(
            "services.orchestrator.src.orchestrator.main.PromptManager",
            return_value=pm,
        ),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        from services.orchestrator.src.orchestrator.main import app

        with TestClient(app) as tc:
            yield tc


def _inject_mocks(client, mock_llm=None, mock_prompt=None):
    """Set mock instances on app state."""
    client.app.state.llm_client = mock_llm or MagicMock()
    client.app.state.prompt_manager = mock_prompt or MagicMock()


class MockLLM:
    def __init__(self, tokens=None):
        self._tokens = tokens or ["mock ", "response"]
        self.captured_kwargs = None

    async def generate(self, messages, _stream=True, _max_tokens=None, _temperature=None):
        self.captured_kwargs = {"messages": messages}
        for t in self._tokens:
            yield t


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def mock_prompt():
    pm = MagicMock()
    pm.render = MagicMock(return_value="You are a helpful assistant.")
    return pm


def test_chat_returns_sse_stream(client, mock_prompt):
    tokens = ["Hello", " ", "world", "!"]
    llm = MockLLM(tokens)
    _inject_mocks(client, llm, mock_prompt)

    response = client.post(
        "/chat",
        json={"message": "say hello"},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = response.text
    for tok in tokens:
        assert tok in data
    assert "[DONE]" in data


def test_chat_without_message_returns_422(client):
    response = client.post("/chat", json={})
    assert response.status_code == 422


def test_chat_with_empty_message_returns_422(client):
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_includes_prompt_in_generate_call(client, mock_prompt):
    mock_prompt.render.return_value = "System prompt content"
    llm = MockLLM()
    _inject_mocks(client, llm, mock_prompt)

    client.post("/chat", json={"message": "hello"})

    mock_prompt.render.assert_called_once_with(
        max_tokens="512",
        retrieved_memory="",
        short_term_buffer="",
    )
    assert llm.captured_kwargs is not None
    msgs = llm.captured_kwargs["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "System prompt content"}
    assert msgs[1] == {"role": "user", "content": "hello"}
