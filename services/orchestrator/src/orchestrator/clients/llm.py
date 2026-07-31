from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx
from shared.config import LLMConfig


class LLMError(Exception): ...


class ModelNotFoundError(LLMError): ...


class ServiceUnavailableError(LLMError): ...


class OllamaConnectionError(LLMError): ...


class OllamaAPIError(LLMError): ...


class OllamaError(LLMError): ...


class BaseLLMClient(ABC):
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]: ...


class GroqClient(BaseLLMClient):
    """Groq LLM client using OpenAI-compatible API."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        self._api_key = config.groq.api_key
        self._model = config.groq.model or "llama-3.1-70b-versatile"
        self._base_url = "https://api.groq.com/openai/v1"
        self._timeout = 30
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._http

    async def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        client = await self._get_client()
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens or 512,
        }

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code >= 400:
                error_text = await resp.aread()
                raise LLMError(
                    f"Groq API error: {resp.status_code} "
                    f"{error_text.decode(errors='replace')}"
                )

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    yield token

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None


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

    async def _try_generate(self, payload: dict) -> AsyncIterator[str]:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client,
            client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload
            ) as response,
        ):
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
            except (httpx.ConnectError, httpx.TimeoutException) as e:
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
            return GroqClient(config)
        case "gemini":
            raise NotImplementedError("Gemini client not yet implemented")
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
