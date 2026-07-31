from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from shared.logging import get_logger

logger = get_logger("orchestrator.clients.tts")


class TTSClientError(Exception):
    pass


class TTSClient:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._http

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio. Returns complete WAV bytes."""
        client = await self._get_client()
        resp = await client.post("/synthesize", json={"text": text})
        if resp.status_code >= 400:
            raise TTSClientError(f"synthesize failed: {resp.status_code} {resp.text}")
        return resp.content

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Synthesize text to audio and stream chunks.

        Yields raw PCM audio chunks as they arrive from the TTS service.
        Each chunk is ~200ms of audio.
        """
        # Accumulate the full response and chunk it here.
        audio_bytes = await self.synthesize(text)

        if not audio_bytes:
            return

        # Strip WAV header to get raw PCM
        data_start = 0
        data_size = len(audio_bytes)

        if audio_bytes[:4] == b"RIFF":
            # Find data chunk
            pos = 12
            while pos + 8 <= len(audio_bytes):
                chunk_id = audio_bytes[pos : pos + 4]
                chunk_size = int.from_bytes(audio_bytes[pos + 4 : pos + 8], "little")
                if chunk_id == b"data":
                    data_start = pos + 8
                    data_size = chunk_size
                    break
                pos += 8 + chunk_size
                if chunk_size % 2 != 0:
                    pos += 1

        raw_pcm = audio_bytes[data_start : data_start + data_size]

        # Chunk into ~200ms frames
        chunk_size = 3200  # 200ms at 16kHz 16-bit mono
        for i in range(0, len(raw_pcm), chunk_size):
            yield raw_pcm[i : i + chunk_size]

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
