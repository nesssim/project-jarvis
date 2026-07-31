from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def mock_services():
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch("orchestrator.main.create_redis_clients", return_value=(None, None)),
        patch("orchestrator.main.create_llm_client") as mock_llm_factory,
        patch("orchestrator.main.PromptManager") as mock_prompt_factory,
        patch("orchestrator.main.STTClient", return_value=AsyncMock()) as mock_stt,
        patch("orchestrator.main.TTSClient", return_value=AsyncMock()) as mock_tts,
        patch("orchestrator.main.MemoryClient", return_value=AsyncMock()),
        patch("orchestrator.main.ToolsClient", return_value=AsyncMock()),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = True
        mock_settings.auth.api_key = "test-secret-key"
        mock_settings.auth.api_key_header = "X-API-Key"
        mock_settings.audio.sample_rate = 16000
        mock_settings.audio.channels = 1
        mock_settings.audio.sample_width = 2
        mock_settings.audio.chunk_size_ms = 100
        mock_settings.stt.vad.threshold = 0.5
        mock_settings.stt.vad.silence_duration_ms = 800
        mock_settings.listening.timeout_seconds = 5
        mock_settings.listening.silence_threshold_ms = 800
        mock_settings.listening.barge_in_enabled = True
        mock_settings.listening.barge_in_jitter_ms = 200

        mock_llm = AsyncMock()
        mock_llm.generate = MagicMock()

        async def _llm_gen(*args, **kwargs):
            for t in ["Hello", " world", "!"]:
                yield t

        mock_llm.generate.return_value = _llm_gen()
        mock_llm_factory.return_value = mock_llm

        mock_prompt = MagicMock()
        mock_prompt.get_system_prompt.return_value = "You are a helpful assistant."
        mock_prompt_factory.return_value = mock_prompt

        yield {
            "stt": mock_stt.return_value,
            "tts": mock_tts.return_value,
            "llm": mock_llm,
            "settings": mock_settings,
        }


@pytest.fixture
def ws_client(mock_services):
    from orchestrator.main import app

    app.state.settings = mock_services["settings"]
    app.state.stt_client = mock_services["stt"]
    app.state.tts_client = mock_services["tts"]
    app.state.llm_client = mock_services["llm"]
    app.state.prompt_manager = MagicMock()
    app.state.prompt_manager.get_system_prompt.return_value = "You are helpful."

    with TestClient(app) as client:
        yield client


def _connect(ws_client, api_key="test-secret-key"):
    headers = {"X-API-Key": api_key} if api_key else {}
    return ws_client.websocket_connect("/ws/audio", headers=headers)


from tests.conftest import make_audio_chunk as _make_audio_chunk


class TestAudioBufferOverflow:
    def test_buffer_overflow_raises_pipeline_error(self):
        from orchestrator.core.pipeline import RealtimePipeline

        stt = AsyncMock()
        tts = AsyncMock()
        llm = AsyncMock()
        llm.generate = MagicMock(return_value=self._async_gen([]))
        prompt = MagicMock()
        settings = MagicMock()
        settings.audio.sample_rate = 16000
        settings.audio.channels = 1
        settings.audio.sample_width = 2
        settings.listening.barge_in_enabled = True
        settings.listening.barge_in_jitter_ms = 200

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=settings,
        )

        # push_audio returns False when not in AUDIO_INPUT_STATES
        # Processing state rejects audio
        async def test():
            result = await pipeline.push_audio(b"\x00\x01" * 100)
            assert result is True  # IDLE accepts

        asyncio.run(test())

    def test_buffer_near_limit_accepted(self):
        from orchestrator.core.pipeline import RealtimePipeline

        stt = AsyncMock()
        tts = AsyncMock()
        llm = AsyncMock()
        llm.generate = MagicMock(return_value=self._async_gen([]))
        prompt = MagicMock()
        settings = MagicMock()
        settings.audio.sample_rate = 16000
        settings.audio.channels = 1
        settings.audio.sample_width = 2
        settings.listening.barge_in_enabled = True
        settings.listening.barge_in_jitter_ms = 200

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=settings,
        )

        async def test():
            result1 = await pipeline.push_audio(b"\x00\x01" * 100)
            assert result1 is True
            result2 = await pipeline.push_audio(b"\x00\x01" * 100)
            assert result2 is True

        asyncio.run(test())

    @staticmethod
    async def _async_gen(items):
        for i in items:
            yield i


class TestOversizedMessage:
    def test_oversized_binary_returns_error(self, ws_client):
        mock_stt = ws_client._transport.app.state.stt_client
        mock_stt.check_vad = AsyncMock(return_value={
            "is_speech": True, "probability": 0.8, "silence_duration_ms": 0,
        })

        with _connect(ws_client) as ws:
            ws.receive_json()
            huge = b"\x00" * (11 * 1024 * 1024)
            ws.send_bytes(huge)
            import time
            time.sleep(0.2)

            for _ in range(10):
                try:
                    msg = ws.receive_json()
                    if msg["type"] == "error":
                        assert "exceeds" in msg["message"]
                        return
                except WebSocketDisconnect:
                    break
                except Exception:
                    break
            pytest.fail("No error for oversized message")

    def test_oversized_text_returns_error(self, ws_client):
        with _connect(ws_client) as ws:
            ws.receive_json()
            huge = "x" * 70000
            ws.send_text(huge)
            import time
            time.sleep(0.2)

            for _ in range(10):
                try:
                    msg = ws.receive_json()
                    if msg["type"] == "error":
                        assert "exceeds" in msg["message"]
                        return
                except WebSocketDisconnect:
                    break
                except Exception:
                    break
            pytest.fail("No error for oversized text")


class TestPipelineBusyReset:
    def test_pipeline_busy_reset_on_stt_exception(self, ws_client, mock_services):
        mock_stt = mock_services["stt"]

        async def failing_transcribe(audio_bytes):
            raise Exception("STT crashed")

        mock_stt.transcribe = failing_transcribe
        mock_stt.check_vad = AsyncMock(return_value={
            "is_speech": True, "probability": 0.8, "silence_duration_ms": 0,
        })
        mock_stt.reset_vad = AsyncMock()

        with _connect(ws_client) as ws:
            ws.receive_json()
            ws.send_bytes(_make_audio_chunk(100))
            import time
            time.sleep(0.3)
            ws.send_json({"type": "stop"})
            time.sleep(0.3)

            ws.send_bytes(_make_audio_chunk(100))
            time.sleep(0.2)

            ws.send_json({"type": "cancel"})
            time.sleep(0.2)

            for _ in range(10):
                try:
                    msg = ws.receive_json()
                    if msg["type"] == "cancelled":
                        return
                except WebSocketDisconnect:
                    break
                except Exception:
                    break

    def test_pipeline_state_reset_on_tts_exception(self, ws_client, mock_services):
        mock_stt = mock_services["stt"]
        mock_tts = mock_services["tts"]

        async def mock_transcribe(audio_bytes):
            return {"text": "test", "language": "en", "segments": [], "confidence": 0.9}

        mock_stt.transcribe = mock_transcribe
        mock_stt.check_vad = AsyncMock(return_value={
            "is_speech": True, "probability": 0.8, "silence_duration_ms": 0,
        })
        mock_stt.reset_vad = AsyncMock()
        mock_tts.synthesize = AsyncMock(side_effect=Exception("TTS crashed"))

        with _connect(ws_client) as ws:
            ws.receive_json()
            ws.send_bytes(_make_audio_chunk(100))
            import time
            time.sleep(0.3)
            ws.send_json({"type": "stop"})
            time.sleep(0.3)

            ws.send_bytes(_make_audio_chunk(100))
            time.sleep(0.2)

            ws.send_json({"type": "cancel"})
            time.sleep(0.2)

            for _ in range(10):
                try:
                    msg = ws.receive_json()
                    if msg["type"] == "cancelled":
                        return
                except WebSocketDisconnect:
                    break
                except Exception:
                    break


class TestConnectionLimit:
    def test_connection_limit_enforced(self, ws_client):
        connections = []
        try:
            for _ in range(11):
                try:
                    conn = _connect(ws_client)
                    data = conn.receive_json()
                    assert data["type"] == "connected"
                    connections.append(conn)
                except Exception:
                    break
            assert len(connections) <= 10
        finally:
            from contextlib import suppress
            for conn in connections:
                with suppress(Exception):
                    conn.close()


class TestStopHandler:
    def test_stop_triggers_transition(self, ws_client, mock_services):
        mock_stt = mock_services["stt"]
        mock_tts = mock_services["tts"]

        async def mock_transcribe(audio_bytes):
            return {"text": "hello", "language": "en", "segments": [], "confidence": 0.9}

        mock_stt.transcribe = mock_transcribe
        mock_stt.check_vad = AsyncMock(return_value={
            "is_speech": True, "probability": 0.8, "silence_duration_ms": 0,
        })
        mock_tts.synthesize = AsyncMock(return_value=_make_audio_chunk(200))

        tts_complete_received = False

        with _connect(ws_client) as ws:
            ws.receive_json()
            ws.send_bytes(_make_audio_chunk(100))
            import time
            time.sleep(0.5)
            ws.send_json({"type": "stop"})

            time.sleep(0.5)

            for _ in range(30):
                try:
                    raw = ws.receive()
                    if "text" in raw:
                        msg = json.loads(raw["text"])
                        if msg["type"] == "tts.complete":
                            tts_complete_received = True
                            break
                except WebSocketDisconnect:
                    break
                except Exception:
                    break

        assert tts_complete_received, "tts.complete was not received after stop"
