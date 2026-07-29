from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from shared.config import LLMConfig, Settings

from services.orchestrator.src.orchestrator.clients.llm import (
    BaseLLMClient,
    create_llm_client,
)


def test_create_llm_client_ollama() -> None:
    settings = Settings(llm={"provider": "ollama"})
    client = create_llm_client(settings.llm)
    assert isinstance(client, BaseLLMClient)
    assert client.config.provider == "ollama"


def test_ollama_client_config_mapped() -> None:
    settings = Settings(llm={"provider": "ollama", "ollama": {"model": "test-model"}})
    client = create_llm_client(settings.llm)
    assert isinstance(client, BaseLLMClient)
    assert client.config.ollama.model == "test-model"
    assert client.config.generation.max_tokens == 512


def test_create_llm_client_groq_not_implemented() -> None:
    settings = Settings(
        llm={"provider": "groq", "groq": {"api_key": "test-key"}}
    )
    with pytest.raises(NotImplementedError, match="Groq"):
        create_llm_client(settings.llm)


def test_create_llm_client_gemini_not_implemented() -> None:
    settings = Settings(
        llm={"provider": "gemini", "gemini": {"api_key": "test-key"}}
    )
    with pytest.raises(NotImplementedError, match="Gemini"):
        create_llm_client(settings.llm)


class _ConcreteClient(BaseLLMClient):
    async def generate(
        self,
        _messages: list[dict[str, str]] | None = None,
        _stream: bool = True,
        _max_tokens: int | None = None,
        _temperature: float | None = None,
    ) -> AsyncIterator[str]:
        yield "test"


def test_concrete_client_generates() -> None:
    config = LLMConfig(provider="ollama")
    client = _ConcreteClient(config)
    assert client.config == config
    assert client.config.ollama.model == "qwen2.5:8b"
