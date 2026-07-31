from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from stt.routes import vad_check as vc_module
from stt.vad import VADError, VADEvent, VADEventType


class _FakeVad:
    def __init__(self) -> None:
        self.process_result = VADEvent(VADEventType.SPEECH, 0.1, 0.7)
        self.process_error: VADError | None = None
        self.is_speaking = False
        self.last_probability = 0.7
        self.silence_ms = 100.0
        self.reset_calls = 0
        self.processed: list[bytes] = []

    def process(self, audio: bytes) -> VADEvent | None:
        self.processed.append(audio)
        if self.process_error is not None:
            raise self.process_error
        return self.process_result

    def reset(self) -> None:
        self.reset_calls += 1


def _make_request(body: bytes) -> Request:
    scope: dict = {
        "type": "http",
        "method": "POST",
        "path": "/vad",
        "raw_path": b"/vad",
        "query_string": b"",
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


@pytest.fixture(autouse=True)
def vad_check_env(monkeypatch: pytest.MonkeyPatch):
    fake_vad = _FakeVad()

    monkeypatch.setattr(vc_module, "_VAD_INSTANCES", {})
    monkeypatch.setattr(vc_module, "VADProcessor", MagicMock(return_value=fake_vad))

    mock_settings = MagicMock()
    mock_settings.stt.vad.threshold = 0.5
    mock_settings.stt.vad.silence_duration_ms = 800
    mock_settings.stt.vad.max_instances = 10
    monkeypatch.setattr(
        vc_module, "load_settings", MagicMock(return_value=mock_settings)
    )

    return fake_vad


def _wav_body(pcm: bytes) -> bytes:
    fmt_payload = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    riff_size = 4 + (8 + len(fmt_payload)) + (8 + len(pcm))
    return (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt_payload))
        + fmt_payload
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


class TestVadCheckRoute:
    async def test_empty_body_returns_400(self, vad_check_env) -> None:  # noqa: ARG002
        with pytest.raises(HTTPException) as exc:
            await vc_module.check_vad(_make_request(b""))
        assert exc.value.status_code == 400
        assert "No audio data provided" in exc.value.detail

    async def test_short_body_returns_zeroed_response(
        self, vad_check_env  # noqa: ARG002
    ) -> None:
        result = await vc_module.check_vad(_make_request(b"\x00\x00" * 79))
        assert result.is_speech is False
        assert result.probability == 0.0
        assert result.silence_duration_ms == 0.0

    async def test_raw_pcm_detects_speech(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        result = await vc_module.check_vad(_make_request(b"\x00\x00" * 256))
        assert result.is_speech is True
        assert result.probability == 0.7
        assert result.silence_duration_ms == 100.0
        assert fake_vad.processed == [b"\x00\x00" * 256]

    async def test_wav_body_strips_header(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        pcm = b"\x00\x00" * 256
        await vc_module.check_vad(_make_request(_wav_body(pcm)))
        assert fake_vad.processed == [pcm]

    async def test_malformed_wav_falls_back_to_full_body(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        body = b"RIFF" + b"x" * 160
        await vc_module.check_vad(_make_request(body))
        assert fake_vad.processed == [body]

    async def test_vad_error_returns_400(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        fake_vad.process_error = VADError("boom")
        with pytest.raises(HTTPException) as exc:
            await vc_module.check_vad(_make_request(b"\x00\x00" * 256))
        assert exc.value.status_code == 400
        assert "boom" in exc.value.detail

    async def test_speech_start_event_marks_is_speech(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        fake_vad.process_result = VADEvent(VADEventType.SPEECH_START, 0.1, 0.9)
        result = await vc_module.check_vad(_make_request(b"\x00\x00" * 256))
        assert result.is_speech is True


class TestVadCheckSessions:
    async def test_session_id_is_reused(self, vad_check_env) -> None:  # noqa: ARG002
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "s1")
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "s1")
        assert vc_module.VADProcessor.call_count == 1

    async def test_different_sessions_create_separate_instances(
        self, vad_check_env  # noqa: ARG002
    ) -> None:
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "a")
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "b")
        assert vc_module.VADProcessor.call_count == 2

    async def test_max_instances_reached_returns_400(
        self, vad_check_env  # noqa: ARG002
    ) -> None:
        vc_module.load_settings.return_value.stt.vad.max_instances = 1
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "a")
        with pytest.raises(VADError, match="Maximum VAD sessions reached"):
            await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "b")

    async def test_ttl_eviction_recreates_instance(
        self, vad_check_env, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        timestamps = iter([1000.0, 1000.0, 1301.0, 1301.0])
        monkeypatch.setattr(
            vc_module, "time", SimpleNamespace(monotonic=lambda: next(timestamps))
        )
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "s1")
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "s1")
        assert vc_module.VADProcessor.call_count == 2

    async def test_reset_endpoint(self, vad_check_env) -> None:
        fake_vad = vad_check_env
        await vc_module.check_vad(_make_request(b"\x00\x00" * 256), "s1")
        result = await vc_module.reset_vad("s1")
        assert result == {"status": "ok"}
        assert fake_vad.reset_calls == 1
