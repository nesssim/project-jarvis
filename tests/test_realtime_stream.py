from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_audio_chunk(duration_ms: int = 100) -> bytes:
    """Generate synthetic PCM 16-bit mono 16kHz audio (440Hz sine)."""
    import math

    sample_rate = 16000
    num_samples = sample_rate * duration_ms // 1000
    samples = bytearray()
    for i in range(num_samples):
        val = int(math.sin(2 * math.pi * 440 * i / sample_rate) * 8000)
        samples.extend(val.to_bytes(2, "little", signed=True))
    return bytes(samples)


class _StatefulVAD:
    """VAD mock that returns controlled speech detection results.

    VAD state is tracked across calls so tests can simulate speech-start
    followed by silence or vice versa.
    """

    def __init__(self) -> None:
        self._call_count = 0
        self.speech_pattern: list[bool] | None = None
        self._default_speech = True

    def set_speech_pattern(self, pattern: list[bool]) -> None:
        self.speech_pattern = pattern
        self._call_count = 0

    async def check_vad(
        self, _audio_chunk: bytes, session_id: str | None = None
    ) -> dict:
        if self.speech_pattern is not None:
            idx = min(self._call_count, len(self.speech_pattern) - 1)
            is_speech = self.speech_pattern[idx]
        else:
            is_speech = self._default_speech
        self._call_count += 1
        return {
            "is_speech": is_speech,
            "probability": 0.9 if is_speech else 0.1,
            "silence_duration_ms": 0 if is_speech else 1000,
        }

    async def transcribe(self, _audio_bytes: bytes) -> dict:
        return {"text": "hello world", "confidence": 0.95, "language": "en"}

    async def reset_vad(self, session_id: str | None = None) -> None:
        self._call_count = 0

    async def close(self) -> None:
        pass


class _MockLLM:
    """Mock LLM yielding predefined token sequence."""

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["Hello", " world", "!"]
        self.config = type(
            "obj",
            (object,),
            {"generation": type("obj", (object,), {"max_tokens": 2048})},
        )()

    async def generate(
        self,
        _messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        for token in self.tokens:
            yield token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_services():
    """Patch all orchestrator dependencies with mocks."""
    with (
        patch("orchestrator.main.settings") as mock_settings,
        patch("orchestrator.main.create_redis_clients", return_value=(None, None)),
        patch("orchestrator.main.create_llm_client") as mock_llm_factory,
        patch("orchestrator.main.PromptManager") as mock_prompt_factory,
        patch("orchestrator.main.STTClient") as mock_stt_factory,
        patch("orchestrator.main.TTSClient") as mock_tts_factory,
        patch("orchestrator.main.MemoryClient", return_value=AsyncMock()),
        patch("orchestrator.main.ToolsClient", return_value=AsyncMock()),
    ):
        mock_settings.rate_limiting.default = "100/minute"
        mock_settings.auth.enabled = False
        mock_settings.audio.sample_rate = 16000
        mock_settings.audio.channels = 1
        mock_settings.audio.sample_width = 2
        mock_settings.listening.timeout_seconds = 5
        mock_settings.listening.silence_threshold_ms = 800
        mock_settings.listening.barge_in_enabled = True
        mock_settings.listening.barge_in_jitter_ms = 10

        mock_llm = _MockLLM(
            tokens=[
                "Hello",
                " world! ",
                "This is a",
                " test. ",
                "Another sentence. ",
                "And one more!",
            ]
        )
        mock_llm_factory.return_value = mock_llm

        mock_prompt = MagicMock()
        mock_prompt.get_system_prompt.return_value = "You are a helpful assistant."
        mock_prompt_factory.return_value = mock_prompt

        mock_stt = _StatefulVAD()
        mock_stt_factory.return_value = mock_stt

        async def _synthesize(_sentence: str) -> bytes:
            await asyncio.sleep(0.25)
            return _make_audio_chunk(500)

        mock_tts = AsyncMock()
        mock_tts.synthesize = _synthesize
        mock_tts_factory.return_value = mock_tts

        yield {
            "stt": mock_stt,
            "tts": mock_tts,
            "llm": mock_llm,
            "settings": mock_settings,
            "prompt": mock_prompt,
        }


@pytest.fixture
def ws_client(mock_services):
    """FastAPI TestClient with mocked services injected into app state."""
    from orchestrator.main import app

    app.state.settings = mock_services["settings"]
    app.state.stt_client = mock_services["stt"]
    app.state.tts_client = mock_services["tts"]
    app.state.llm_client = mock_services["llm"]
    app.state.prompt_manager = mock_services["prompt"]
    app.state.memory_client = AsyncMock()
    app.state.tools_client = AsyncMock()

    from orchestrator.routes.ws import _active_connections

    _active_connections.clear()

    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receive_ws(ws, timeout: float = 3.0) -> dict | None:
    """Receive one WebSocket message, bounded by *timeout* seconds.

    starlette's ``WebSocketTestSession.receive()`` takes no timeout argument
    (since 1.0), so the timeout is applied on the portal's event loop via
    ``asyncio.wait_for``.  Returns the raw message dict, or ``None`` on
    timeout / disconnect.
    """
    portal = ws.portal
    rx = ws._send_rx
    try:
        return portal.call(asyncio.wait_for, rx.receive(), timeout)
    except Exception:
        return None


def _receive_ws_json(ws, timeout: float = 3.0) -> dict | None:
    """Receive one JSON WebSocket message, bounded by *timeout* seconds."""
    raw = _receive_ws(ws, timeout)
    if raw is None or "text" not in raw:
        return None
    return json.loads(raw["text"])


def _receive_any(ws, timeout: float = 3) -> dict | None:
    """Receive one WebSocket message (text or binary).

    Returns parsed JSON dict or ``{"_bytes": True, "size": N}`` for binary.
    Returns ``None`` on disconnect / timeout.
    """
    raw = _receive_ws(ws, timeout)
    if raw is None:
        return None
    if "text" in raw:
        return json.loads(raw["text"])
    if "bytes" in raw:
        return {"_bytes": True, "size": len(raw["bytes"])}
    return None


def _collect_messages(
    ws, *, min_messages: int = 0, timeout_per_msg: float = 3, max_messages: int = 80
) -> list[dict]:
    """Collect WebSocket messages until *max_messages* or a receive timeout."""
    msgs: list[dict] = []
    for _ in range(max_messages):
        raw = _receive_ws(ws, timeout_per_msg)
        if raw is None:
            break
        if "text" in raw:
            msgs.append(json.loads(raw["text"]))
        elif "bytes" in raw:
            msgs.append({"_bytes": True, "size": len(raw["bytes"])})
        if min_messages and len(msgs) >= min_messages:
            break
    return msgs


def _wait_for_type(
    ws, expected: str, timeout: float = 5, drop_binary: bool = True
) -> dict | None:
    """Receive messages until a JSON message with the given *type* is seen.

    Returns the matching message dict, or ``None`` on timeout / disconnect.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        raw = _receive_ws(ws, max(0.1, remaining))
        if raw is None:
            break
        if "text" in raw:
            msg = json.loads(raw["text"])
            if msg["type"] == expected:
                return msg
        # binary: drop and continue
    return None


def _json_types(msgs: list[dict]) -> list[str]:
    """Return the ``type`` field of every JSON message in the list."""
    return [m["type"] for m in msgs if "type" in m]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicFlow:
    """Happy path: IDLE -> LISTENING -> PROCESSING -> SPEAKING -> IDLE."""

    def test_basic_happy_path(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True, True, True, True])

        with ws_client.websocket_connect("/ws/audio") as ws:
            # 1. Connected
            msg = _wait_for_type(ws, "connected", timeout=3)
            assert msg is not None
            assert "session_id" in msg

            # 2. Send audio -> VAD speech start
            ws.send_bytes(_make_audio_chunk(200))
            msg = _wait_for_type(ws, "vad.speech_start", timeout=3)
            assert msg is not None

            # 3. Send more audio while listening
            for _ in range(5):
                ws.send_bytes(_make_audio_chunk(200))

            # 4. Stop utterance
            ws.send_text(json.dumps({"type": "stop"}))

            # 5. vad.speech_end
            msg = _wait_for_type(ws, "vad.speech_end", timeout=5)
            assert msg is not None

            # 6. Collect remaining messages
            msgs = _collect_messages(ws, timeout_per_msg=5, max_messages=80)
            types = _json_types(msgs)

            # Verify pipeline milestones
            assert "transcript.final" in types, f"missing transcript.final in {types}"
            assert "llm.token" in types, f"missing llm.token in {types}"
            assert "llm.complete" in types, f"missing llm.complete in {types}"
            assert "tts.start" in types, f"missing tts.start in {types}"
            assert "tts.complete" in types, f"missing tts.complete in {types}"

            # Verify binary audio was sent
            binary_count = sum(1 for m in msgs if m.get("_bytes"))
            assert binary_count > 0, "no binary audio chunks received"

            # Verify order constraints
            tts_start_idx = types.index("tts.start")
            tts_complete_idx = types.index("tts.complete")
            assert (
                tts_start_idx < tts_complete_idx
            ), "tts.start must precede tts.complete"


class TestBargeIn:
    """User interrupts during TTS playback."""

    def test_barge_in_during_tts(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True, True, True, True, True])

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            # Start utterance
            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            for _ in range(5):
                ws.send_bytes(_make_audio_chunk(200))

            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Wait for TTS to start (pipeline processing LLM -> TTS)
            msg = _wait_for_type(ws, "tts.start", timeout=10)
            assert msg is not None, "tts.start not received"

            # Now send audio while TTS is speaking -> triggers barge-in
            ws.send_bytes(_make_audio_chunk(200))

            # Should receive interrupted event
            msg = _wait_for_type(ws, "interrupted", timeout=5)
            assert msg is not None, "interrupted not received on barge-in"

            # Should receive a new vad.speech_start for the barge-in audio
            msg = _wait_for_type(ws, "vad.speech_start", timeout=3)
            assert msg is not None, "vad.speech_start not received after barge-in"


class TestCancel:
    """Cancel at various FSM stages."""

    def test_cancel_during_processing(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True])

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Cancel while pipeline is processing
            ws.send_text(json.dumps({"type": "cancel"}))

            msg = _wait_for_type(ws, "cancelled", timeout=5)
            assert msg is not None, "cancelled not received"

    def test_cancel_during_listening(self, ws_client) -> None:
        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            # Cancel while still listening
            ws.send_text(json.dumps({"type": "cancel"}))

            msg = _wait_for_type(ws, "cancelled", timeout=5)
            assert msg is not None, "cancelled not received"


class TestListeningTimeout:
    """Listening timeout fires when no speech is detected."""

    def test_timeout_triggers_timeout_event(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True])

        # Override timeout to a small value for fast test
        ws_client.app.state.settings.listening.timeout_seconds = 1

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            # Do NOT send more audio or stop - timeout should fire
            msg = _wait_for_type(ws, "listening.timeout", timeout=5)
            assert (
                msg is not None
            ), "listening.timeout not received after timeout_seconds"


class TestErrorRecovery:
    """STT / LLM / TTS failures transition to ERROR and recover."""

    def test_stt_failure_transitions_to_error(self, ws_client, mock_services) -> None:
        mock_stt = mock_services["stt"]
        mock_stt.set_speech_pattern([True])

        # Raise on transcribe to trigger STT failure
        mock_stt.transcribe = AsyncMock(side_effect=Exception("STT crashed"))

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Should get an error when STT fails
            msg = _wait_for_type(ws, "error", timeout=5)
            assert msg is not None, "error not received after STT failure"
            assert "STT failed" in msg.get(
                "message", ""
            ), f"unexpected error message: {msg}"

    def test_error_recovery_resets_to_idle(self, ws_client, mock_services) -> None:
        mock_stt = mock_services["stt"]
        mock_stt.set_speech_pattern([True])

        mock_stt.transcribe = AsyncMock(side_effect=Exception("STT crashed"))

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Wait for error
            msg = _wait_for_type(ws, "error", timeout=5)
            assert msg is not None

            # Cancel should recover to IDLE
            ws.send_text(json.dumps({"type": "cancel"}))

            msg = _wait_for_type(ws, "cancelled", timeout=5)
            assert msg is not None, "cancelled not received after error recovery"


class TestDisconnectCleanup:
    """Client disconnect mid-session triggers graceful cleanup."""

    def test_disconnect_during_speech_cleans_up(self, ws_client) -> None:
        with ws_client.websocket_connect("/ws/audio") as ws:
            msg = _receive_ws_json(ws, timeout=3)
            assert msg is not None
            assert msg["type"] == "connected"

            ws.send_bytes(_make_audio_chunk(200))
            msg = _receive_ws_json(ws, timeout=3)
            assert msg is not None
            assert msg["type"] == "vad.speech_start"

            # Disconnect — connection closes, WS handler cleans up
        # If we reach here without exception the cleanup was graceful.
        # Verify app state is still valid for subsequent operations.
        assert ws_client.app.state.stt_client is not None


class TestStateTransitions:
    """Edge-case FSM transitions."""

    def test_double_stop_ignored(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True])

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            # Stop once
            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Stop again — should be silently ignored (state != LISTENING)
            ws.send_text(json.dumps({"type": "stop"}))

            # Pipeline should still complete normally
            msgs = _collect_messages(ws, timeout_per_msg=5, max_messages=60)
            types = _json_types(msgs)
            assert (
                "llm.complete" in types
            ), f"pipeline did not complete after double stop: {types}"

    def test_audio_during_processing_triggers_barge_in(self, ws_client) -> None:
        mock_stt = ws_client.app.state.stt_client
        mock_stt.set_speech_pattern([True, True, True, True, True, True])

        with ws_client.websocket_connect("/ws/audio") as ws:
            _wait_for_type(ws, "connected", timeout=3)

            ws.send_bytes(_make_audio_chunk(200))
            _wait_for_type(ws, "vad.speech_start", timeout=3)

            for _ in range(5):
                ws.send_bytes(_make_audio_chunk(200))

            ws.send_text(json.dumps({"type": "stop"}))
            _wait_for_type(ws, "vad.speech_end", timeout=5)

            # Right after stop, pipeline transitions to PROCESSING.
            # Send audio while processing should trigger barge-in
            ws.send_bytes(_make_audio_chunk(200))

            msg = _wait_for_type(ws, "interrupted", timeout=5)
            assert msg is not None, "barge-in not triggered during PROCESSING"
