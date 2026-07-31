from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from shared.audio import FileAudioSource, NullAudioSink

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audio"


@pytest.fixture
def voice_pipeline():
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

        class MockLLM:
            def __init__(self):
                self.config = type(
                    "obj",
                    (object,),
                    {"generation": type("obj", (object,), {"max_tokens": 2048})},
                )()

            async def generate(
                self, messages, stream=True, max_tokens=None, temperature=None
            ):
                yield "The weather is sunny and 72 degrees."

        mock_create_llm.return_value = MockLLM()
        pm_instance = MagicMock()
        pm_instance.render.return_value = "You are a voice assistant."
        mock_pm.return_value = pm_instance

        class MockSTT:
            async def transcribe(self, audio_bytes):
                return {
                    "text": "what is the weather",
                    "language": "en",
                    "segments": [],
                    "confidence": 0.95,
                }

            async def close(self):
                pass

        class MockTTS:
            async def synthesize(self, text):
                return b"\x00" * 32000

            async def close(self):
                pass

        mock_stt_cls.return_value = MockSTT()
        mock_tts_cls.return_value = MockTTS()

        from orchestrator.main import app

        app.state.stt_client = MockSTT()
        app.state.tts_client = MockTTS()
        app.state.llm_client = MockLLM()
        app.state.prompt_manager = pm_instance
        app.state.memory_client = AsyncMock()
        app.state.tools_client = AsyncMock()

        with TestClient(app) as client:
            yield client


class TestTurnBasedE2E:
    def test_clean_speech_round_trip(self, voice_pipeline):
        fixture = FIXTURES / "speech_clean_16khz.wav"
        assert fixture.exists(), f"Fixture not found: {fixture}"

        audio_data = fixture.read_bytes()

        t0 = time.perf_counter()
        response = voice_pipeline.post(
            "/voice", content=audio_data, headers={"Content-Type": "audio/wav"}
        )
        elapsed = time.perf_counter() - t0

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert len(response.content) > 0
        assert float(response.headers.get("X-Confidence", "0")) > 0
        assert elapsed < 5.0

    def test_source_to_sink_round_trip(self, voice_pipeline):
        fixture = FIXTURES / "speech_clean_16khz.wav"

        with FileAudioSource(str(fixture)) as source:
            audio_chunks = list(source.read(chunk_size=4096))

        audio_data = b"".join(audio_chunks)

        response = voice_pipeline.post(
            "/voice", content=audio_data, headers={"Content-Type": "audio/wav"}
        )

        assert response.status_code == 200
        response_audio = response.content

        sink = NullAudioSink()
        sink.write(response_audio)
        assert sink.total_bytes_written > 0
        sink.close()

    def test_silence_returns_audio(self, voice_pipeline):
        fixture = FIXTURES / "silence_1s_16khz.wav"
        audio_data = fixture.read_bytes()

        response = voice_pipeline.post(
            "/voice", content=audio_data, headers={"Content-Type": "audio/wav"}
        )

        assert response.status_code == 200
        assert len(response.content) > 0

    def test_round_trip_latency_under_threshold(self, voice_pipeline):
        fixture = FIXTURES / "utterance_short_16khz.wav"
        audio_data = fixture.read_bytes()

        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            response = voice_pipeline.post(
                "/voice", content=audio_data, headers={"Content-Type": "audio/wav"}
            )
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            assert response.status_code == 200

        avg_latency = sum(times) / len(times)
        assert avg_latency < 5.0
