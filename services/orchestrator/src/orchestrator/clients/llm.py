from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx
from shared.config import LLMConfig


class LLMError(Exception):
    ...


class ModelNotFoundError(LLMError):
    ...


class ServiceUnavailableError(LLMError):
    ...


class OllamaConnectionError(LLMError):
    ...


class OllamaAPIError(LLMError):
    ...


class OllamaError(LLMError):
    ...


class BaseLLMClient(ABC):
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        ...


class OllamaClient(BaseLLMClient):
    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self.ollama_config = config.ollama
        self.gen_config = config.generation
        self.base_url = self.ollama_config.url.rstrip("/")

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        return {
            "model": self.ollama_config.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "num_predict": max_tokens or self.gen_config.max_tokens,
                "temperature": temperature or self.gen_config.temperature,
                "top_p": self.gen_config.top_p,
            },
        }

    async def _handle_stream(self, response: httpx.Response) -> AsyncIterator[str]:
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise OllamaError(chunk["error"])
            if chunk.get("done"):
                return
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    async def _try_generate(
        self, payload: dict
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client, client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as response:
            if response.status_code == 404:
                raise ModelNotFoundError(
                    f"Model '{self.ollama_config.model}' not found on Ollama"
                )
            if response.status_code == 503:
                raise ServiceUnavailableError("Ollama is not ready")
            response.raise_for_status()
            async for token in self._handle_stream(response):
                yield token

    async def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        payload = self._build_payload(messages, stream, max_tokens, temperature)
        attempts = 3 if stream else 1

        for attempt in range(attempts):
            try:
                async for token in self._try_generate(payload):
                    yield token
                return
            except (httpx.ConnectError, httpx.TimeoutException) as e:  # noqa: PERF203
                if attempt < attempts - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                raise OllamaConnectionError(
                    f"Failed to connect to Ollama after {attempts} attempts: {e}"
                ) from e
            except httpx.HTTPStatusError as e:
                raise OllamaAPIError(
                    f"Ollama returned {e.response.status_code}: [response body redacted]"
                ) from e


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    match config.provider:
        case "ollama":
            return OllamaClient(config)
        case "groq":
            raise NotImplementedError("Groq client coming in Phase 2")
        case "gemini":
            raise NotImplementedError("Gemini client coming in Phase 2")
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
