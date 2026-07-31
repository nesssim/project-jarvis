from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from shared.logging import get_logger

logger = get_logger("orchestrator.clients.stt")


class STTClientError(Exception):
    pass


class STTClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._http

    async def transcribe(self, audio_bytes: bytes) -> dict:
        client = await self._get_client()
        resp = await client.post(
            "/transcribe", content=audio_bytes, headers={"Content-Type": "audio/wav"}
        )
        if resp.status_code >= 400:
            raise STTClientError(f"transcribe failed: {resp.status_code} {resp.text}")
        return resp.json()

    async def check_vad(
        self, audio_chunk: bytes, session_id: str | None = None
    ) -> dict:
        """Check VAD state for an audio chunk.

        Sends raw PCM audio to the STT service's VAD endpoint.
        Returns dict with is_speech, probability, silence_duration_ms.
        """
        client = await self._get_client()
        params = {"session_id": session_id} if session_id else {}
        resp = await client.post(
            "/vad",
            content=audio_chunk,
            headers={"Content-Type": "audio/wav"},
            params=params,
        )
        if resp.status_code >= 400:
            raise STTClientError(f"vad check failed: {resp.status_code} {resp.text}")
        return resp.json()

    async def reset_vad(self, session_id: str | None = None) -> None:
        """Reset the VAD processor state on the STT service."""
        client = await self._get_client()
        params = {"session_id": session_id} if session_id else {}
        await client.post("/vad/reset", params=params)

    async def transcribe_stream(
        self, audio_iterator: AsyncIterator[bytes], sample_rate: int = 16000
    ) -> AsyncIterator[dict]:
        """Stream audio to the STT service and receive transcription events.

        Yields dictionaries representing SSE events from the streaming
        transcribe endpoint. Each dict has 'event' and 'data' keys.

        Possible events: vad.speech_start, transcript.partial,
        vad.speech_end, transcript.final, error.
        """
        client = await self._get_client()
        url = f"/transcribe-stream?sample_rate={sample_rate}"

        async with client.stream(
            "POST",
            url,
            content=audio_iterator,
            headers={"Content-Type": "application/octet-stream"},
        ) as response:
            if response.status_code >= 400:
                error_text = await response.aread()
                raise STTClientError(
                    f"transcribe stream failed: {response.status_code} "
                    f"{error_text.decode(errors='replace')}"
                )

            event_type = ""
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    yield {"event": event_type, **data}
                    event_type = ""

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
