from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from shared.config import LLMConfig

from services.orchestrator.src.orchestrator.clients.llm import (
    ModelNotFoundError,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    ServiceUnavailableError,
)


@pytest.fixture
def config() -> LLMConfig:
    return LLMConfig(
        provider="ollama",
        ollama={"url": "http://ollama:11434", "model": "test-model"},
        generation={"max_tokens": 256, "temperature": 0.5, "top_p": 0.8},
    )


@pytest.fixture
def client(config: LLMConfig) -> OllamaClient:
    return OllamaClient(config)


def test_build_payload_defaults(client: OllamaClient) -> None:
    messages = [{"role": "user", "content": "hi"}]
    payload = client._build_payload(messages, stream=True)  # noqa: SLF001
    assert payload["model"] == "test-model"
    assert payload["stream"] is True
    assert payload["messages"] == messages
    assert payload["options"]["num_predict"] == 256
    assert payload["options"]["temperature"] == 0.5
    assert payload["options"]["top_p"] == 0.8


def test_build_payload_overrides(client: OllamaClient) -> None:
    messages = [{"role": "user", "content": "hi"}]
    payload = client._build_payload(messages, stream=False, max_tokens=999, temperature=0.1)  # noqa: SLF001
    assert payload["options"]["num_predict"] == 999
    assert payload["options"]["temperature"] == 0.1


def test_ollama_client_base_url_trailing_slash(config: LLMConfig) -> None:
    config.ollama.url = "http://ollama:11434/"
    c = OllamaClient(config)
    assert c.base_url == "http://ollama:11434"


def test_ollama_client_config_refs(config: LLMConfig, client: OllamaClient) -> None:
    assert client.ollama_config is config.ollama
    assert client.gen_config is config.generation


@pytest.mark.asyncio
async def test_handle_stream_yields_tokens(client: OllamaClient) -> None:
    chunks = [
        json.dumps({"message": {"content": "Hello"}}) + "\n",
        json.dumps({"message": {"content": " world"}}) + "\n",
        json.dumps({"done": True}) + "\n",
    ]

    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.aiter_lines.return_value = AsyncIteratorMock(chunks)

    tokens = [t async for t in client._handle_stream(mock_response)]  # noqa: SLF001
    assert tokens == ["Hello", " world"]


@pytest.mark.asyncio
async def test_handle_stream_raises_on_error(client: OllamaClient) -> None:
    chunks = [json.dumps({"error": "model not loaded"}) + "\n"]
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.aiter_lines.return_value = AsyncIteratorMock(chunks)

    with pytest.raises(OllamaError, match="model not loaded"):
        async for _ in client._handle_stream(mock_response):  # noqa: SLF001
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_generate_connect_error_retries_then_raises(client: OllamaClient) -> None:
    with patch.object(client, "_try_generate") as mock_try:
        mock_try.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(OllamaConnectionError, match="Failed to connect to Ollama after 3 attempts"):
            async for _ in client.generate(messages=[{"role": "user", "content": "hi"}]):
                pass  # pragma: no cover


@pytest.mark.asyncio
async def test_generate_model_not_found(client: OllamaClient) -> None:
    with patch.object(client, "_try_generate") as mock_try:
        mock_try.side_effect = ModelNotFoundError("model 'test-model' not found")

        with pytest.raises(ModelNotFoundError):
            async for _ in client.generate(messages=[{"role": "user", "content": "hi"}]):
                pass  # pragma: no cover


@pytest.mark.asyncio
async def test_generate_service_unavailable(client: OllamaClient) -> None:
    with patch.object(client, "_try_generate") as mock_try:
        mock_try.side_effect = ServiceUnavailableError("Ollama is not ready")

        with pytest.raises(ServiceUnavailableError):
            async for _ in client.generate(messages=[{"role": "user", "content": "hi"}]):
                pass  # pragma: no cover


class AsyncIteratorMock:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):  # noqa: D105
        return self

    async def __anext__(self):  # noqa: D105
        try:
            return next(self._chunks)
        except StopIteration as e:
            raise StopAsyncIteration from e
