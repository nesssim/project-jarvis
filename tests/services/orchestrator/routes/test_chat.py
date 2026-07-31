from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Build a TestClient with mocked LLM client, prompt, memory, and tools."""
    llm = MockLLM()
    pm = MagicMock()
    pm.render = MagicMock(return_value="You are a helpful assistant.")
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch("orchestrator.main.create_redis_clients", return_value=(None, None)),
        patch("orchestrator.main.create_llm_client", return_value=llm),
        patch("orchestrator.main.PromptManager", return_value=pm),
        patch("orchestrator.main.MemoryClient", return_value=AsyncMock()),
        patch("orchestrator.main.ToolsClient", return_value=AsyncMock()),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = False
        from orchestrator.main import app

        with TestClient(app) as tc:
            yield tc


def _inject_mocks(client, mock_llm=None, mock_prompt=None):
    client.app.state.llm_client = mock_llm or MagicMock()
    client.app.state.prompt_manager = mock_prompt or MagicMock()
    client.app.state.memory_client = MockMemoryClient()
    client.app.state.tools_client = MockToolsClient()


class MockMemoryClient:
    def __init__(self):
        self.store_calls = []

    async def store_turn(self, session_id, role, content):
        self.store_calls.append((session_id, role, content))
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
        self.execute_calls = []

    async def execute(self, tool, params=None):
        self.execute_calls.append((tool, params))
        return {
            "results": [
                {"title": "Result", "url": "https://example.com", "snippet": "Snippet"}
            ]
        }

    async def list_tools(self):
        return []

    async def close(self):
        pass


class MockLLM:
    def __init__(self, tokens=None):
        self._tokens = tokens or ["mock ", "response"]
        self.captured_kwargs = None
        self.config = type(
            "obj",
            (object,),
            {"generation": type("obj", (object,), {"max_tokens": 2048})},
        )()

    async def generate(
        self, messages, _stream=True, _max_tokens=None, _temperature=None
    ):
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
        "/chat", json={"message": "say hello"}, headers={"Accept": "text/event-stream"}
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "[DONE]" in response.text


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

    mock_prompt.render.assert_called_once()
    assert llm.captured_kwargs is not None
    msgs = llm.captured_kwargs["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "System prompt content"}
    assert msgs[1] == {"role": "user", "content": "hello"}


def test_chat_returns_session_id(client, mock_prompt):
    llm = MockLLM()
    _inject_mocks(client, llm, mock_prompt)

    response = client.post("/chat", json={"message": "hello"})
    assert "X-Session-ID" in response.headers
    assert len(response.headers["X-Session-ID"]) == 12


def test_chat_with_custom_session_id(client, mock_prompt):
    llm = MockLLM()
    _inject_mocks(client, llm, mock_prompt)

    response = client.post(
        "/chat", json={"message": "hello", "session_id": "my-test-session"}
    )
    assert response.headers["X-Session-ID"] == "my-test-session"


def test_chat_stores_user_and_assistant_turns(client, mock_prompt):
    llm = MockLLM(["response text"])
    _inject_mocks(client, llm, mock_prompt)
    mc = client.app.state.memory_client

    client.post("/chat", json={"message": "hello"})

    assert len(mc.store_calls) >= 2
    assert mc.store_calls[0][1] == "user"
    assert mc.store_calls[0][2] == "hello"
    assert mc.store_calls[1][1] == "assistant"


def test_chat_calls_recall_and_recent(client, mock_prompt):
    llm = MockLLM(["response"])
    mc = MockMemoryClient()
    client.app.state = MagicMock()
    client.app.state.llm_client = llm
    client.app.state.prompt_manager = mock_prompt
    client.app.state.memory_client = mc
    client.app.state.tools_client = MockToolsClient()

    client.post("/chat", json={"message": "hello"})

    assert len(mc.store_calls) >= 1
