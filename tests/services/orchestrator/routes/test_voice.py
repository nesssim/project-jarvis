from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class MockSTTClient:
    def __init__(self):
        self.transcribe_calls = []

    async def transcribe(self, audio_bytes: bytes) -> dict:
        self.transcribe_calls.append(audio_bytes)
        return {
            "text": "hello world",
            "language": "en",
            "segments": [{"text": "hello world", "start": 0, "end": 1.2, "confidence": 0.98}],
            "confidence": 0.98,
        }

    async def close(self):
        pass


class MockTTSClient:
    def __init__(self):
        self.synthesize_calls = []

    async def synthesize(self, text: str) -> bytes:
        self.synthesize_calls.append(text)
        return b"\x00" * 32000

    async def close(self):
        pass


class MockLLM:
    def __init__(self, tokens=None):
        self._tokens = tokens or ["mock ", "response"]
        self.config = type("obj", (object,), {"generation": type("obj", (object,), {"max_tokens": 2048})})()

    async def generate(self, messages, stream=True, max_tokens=None, temperature=None):
        for t in self._tokens:
            yield t


@pytest.fixture
def voice_client():
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch("orchestrator.main.create_redis_clients", return_value=(None, None)),
        patch("orchestrator.main.create_llm_client") as mock_create_llm,
        patch("orchestrator.main.PromptManager") as mock_pm,
        patch("orchestrator.main.STTClient") as mock_stt_cls,
        patch("orchestrator.main.TTSClient") as mock_tts_cls,
        patch("orchestrator.main.MemoryClient", return_value=AsyncMock()),
        patch("orchestrator.main.ToolsClient", return_value=AsyncMock()),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = False
        mock_settings.internal_urls.stt = "http://stt:8001"
        mock_settings.internal_urls.tts = "http://tts:8002"

        mock_llm = MockLLM()
        mock_create_llm.return_value = mock_llm

        pm_instance = MagicMock()
        pm_instance.render.return_value = "You are a voice assistant."
        mock_pm.return_value = pm_instance

        mock_stt_cls.return_value = MockSTTClient()
        mock_tts_cls.return_value = MockTTSClient()

        from orchestrator.main import app

        with TestClient(app) as client:
            client.app.state.stt_client = MockSTTClient()
            client.app.state.tts_client = MockTTSClient()
            client.app.state.llm_client = mock_llm
            client.app.state.prompt_manager = pm_instance
            client.app.state.memory_client = AsyncMock()
            client.app.state.tools_client = AsyncMock()
            yield client


class TestVoicePipeline:
    def test_voice_returns_audio(self, voice_client):
        wav_header = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        audio_bytes = wav_header + b"\x00" * 16000
        response = voice_client.post("/voice", content=audio_bytes, headers={"Content-Type": "audio/wav"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers.get("X-Confidence", "") == "0.98"
        assert len(response.content) > 0

    def test_voice_empty_body_returns_400(self, voice_client):
        response = voice_client.post("/voice", content=b"", headers={"Content-Type": "audio/wav"})
        assert response.status_code == 400

    def test_voice_empty_transcription_returns_empty_audio(self, voice_client):
        voice_client.app.state.stt_client = MockSTTClient()
        voice_client.app.state.stt_client.transcribe = AsyncMock(return_value={"text": "", "confidence": 0})

        response = voice_client.post("/voice", content=b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00" + b"\x00" * 16000, headers={"Content-Type": "audio/wav"})
        assert response.status_code == 200
        assert response.headers.get("X-Confidence", "") == "0"
