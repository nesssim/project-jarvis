from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request
from stt.routes import transcribe_stream as ts_module
from stt.vad import VADError, VADEvent, VADEventType

ZERO_FRAME = b"\x00\x00" * 1600  # 100ms of 16kHz mono PCM (3200 bytes)


class _FakeWhisper:
    def __init__(
        self,
        text: str = "hello world",
        confidence: float = 0.92,
        language: str = "en",
        fail_on_bytes: int | None = None,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.language = language
        self.fail_on_bytes = fail_on_bytes
        self.transcription_sizes: list[int] = []

    def transcribe(self, audio: bytes) -> dict:
        self.transcription_sizes.append(len(audio))
        if self.fail_on_bytes is not None and len(audio) >= self.fail_on_bytes:
            raise RuntimeError("model boom")
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
        }


class _FakeVAD:
    def __init__(self, events: list[VADEvent | None] | None = None) -> None:
        self.events = list(events or [])
        self.silence_duration_ms = 800
        self.raise_on_process: VADError | None = None
        self.reset_calls = 0

    def process(self, _frame: bytes) -> VADEvent | None:
        if self.raise_on_process is not None:
            raise self.raise_on_process
        return self.events.pop(0) if self.events else None

    def reset(self) -> None:
        self.reset_calls += 1


def _make_request(body: bytes, query: str = "") -> Request:
    scope: dict = {
        "type": "http",
        "method": "POST",
        "path": "/transcribe-stream",
        "raw_path": b"/transcribe-stream",
        "query_string": query.encode(),
        "headers": [(b"content-type", b"application/octet-stream")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
        "http_version": "1.1",
    }
    request = Request(scope)
    request._body = body  # noqa: SLF001
    return request


async def _run_stream(request: Request) -> str:
    response = await ts_module.transcribe_stream(request)
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(chunks)


@pytest.fixture(autouse=True)
def stt_stream_env(monkeypatch: pytest.MonkeyPatch):
    whisper = _FakeWhisper()
    vad = _FakeVAD()

    monkeypatch.setattr(ts_module, "_WHISPER_INSTANCE", None)
    monkeypatch.setattr(ts_module, "WhisperSTT", MagicMock(return_value=whisper))
    monkeypatch.setattr(ts_module, "VADProcessor", MagicMock(return_value=vad))

    mock_settings = MagicMock()
    mock_settings.stt.whisper.model_size = "tiny"
    mock_settings.stt.whisper.device = "cpu"
    mock_settings.stt.whisper.compute_type = "int8"
    mock_settings.stt.vad.threshold = 0.5
    mock_settings.stt.vad.silence_duration_ms = 800
    monkeypatch.setattr(
        ts_module, "load_settings", MagicMock(return_value=mock_settings)
    )

    return whisper, vad


class TestTranscribeStreamRoute:
    async def test_happy_path_speech_end(self, stt_stream_env) -> None:
        whisper, vad = stt_stream_env
        vad.events = [
            VADEvent(VADEventType.SPEECH_START, 0.5, 0.9),
            None,
            VADEvent(VADEventType.SPEECH_END, 3.0, 0.1),
        ]

        text = await _run_stream(_make_request(ZERO_FRAME * 3))
        assert "event: vad.speech_start" in text
        assert "event: vad.speech_end" in text
        assert '"silence_duration_ms": 800' in text
        assert "event: transcript.final" in text
        assert '"text": "hello world"' in text
        assert '"confidence": 0.92' in text
        assert '"language": "en"' in text
        assert whisper.transcription_sizes == [len(ZERO_FRAME) * 3]
        assert vad.reset_calls == 1

    async def test_stream_end_transcribes_remaining_audio(self, stt_stream_env) -> None:
        whisper, vad = stt_stream_env
        vad.events = [None, None]

        text = await _run_stream(_make_request(ZERO_FRAME * 2))
        assert "event: transcript.final" in text
        assert "event: vad.speech_start" not in text
        assert whisper.transcription_sizes == [len(ZERO_FRAME) * 2]

    async def test_vad_error_emits_error_event(self, stt_stream_env) -> None:
        _, vad = stt_stream_env
        vad.raise_on_process = VADError("boom")

        text = await _run_stream(_make_request(ZERO_FRAME))
        assert "event: error" in text
        assert "boom" in text

    async def test_final_transcription_failure_emits_error(
        self, stt_stream_env
    ) -> None:
        whisper, vad = stt_stream_env
        whisper.fail_on_bytes = 1
        vad.events = [
            VADEvent(VADEventType.SPEECH_START, 0.5, 0.9),
            VADEvent(VADEventType.SPEECH_END, 1.0, 0.1),
        ]

        text = await _run_stream(_make_request(ZERO_FRAME * 2))
        assert "event: error" in text
        assert "Final transcription failed" in text

    async def test_partials_emitted_during_speech(
        self, stt_stream_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, vad = stt_stream_env
        vad.events = [
            VADEvent(VADEventType.SPEECH_START, 0.5, 0.9),
            None,
            None,
            None,
            None,
            None,
            None,
            VADEvent(VADEventType.SPEECH_END, 4.0, 0.1),
        ]

        fake_time = MagicMock()
        fake_time.time.side_effect = [0.0, 0.0, 0.6, 0.6, 1.2, 1.2, 1.8, 1.8]
        monkeypatch.setattr(ts_module, "time", fake_time)

        text = await _run_stream(_make_request(ZERO_FRAME * 8))
        assert "event: transcript.partial" in text
        assert "event: transcript.final" in text

    async def test_custom_audio_params_resample(self, stt_stream_env) -> None:
        _, vad = stt_stream_env
        vad.events = [None]

        text = await _run_stream(
            _make_request(ZERO_FRAME, query="sample_rate=8000&channels=2")
        )
        assert "event: transcript.final" in text


class TestTranscribeStreamHelpers:
    def test_make_sse_format(self) -> None:
        payload = {"a": 1, "b": "x"}
        sse = ts_module._make_sse("test.event", payload)  # noqa: SLF001
        assert sse == f"event: test.event\ndata: {json.dumps(payload)}\n\n"

    def test_resample_passthrough_16k_mono(self) -> None:
        chunk = ZERO_FRAME
        assert ts_module._resample_to_16k(chunk, 16000, 1, 2) == chunk  # noqa: SLF001

    def test_resample_stereo_to_mono(self) -> None:
        out = ts_module._resample_to_16k(ZERO_FRAME, 16000, 2, 2)  # noqa: SLF001
        assert len(out) == len(ZERO_FRAME) // 2

    def test_resample_8k_mono_upsamples(self) -> None:
        out = ts_module._resample_to_16k(ZERO_FRAME, 8000, 1, 2)  # noqa: SLF001
        assert len(out) == len(ZERO_FRAME) * 2
