from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_stt_deps():
    mock_whisper_module = types.ModuleType("faster_whisper")
    mock_whisper_module.WhisperModel = MagicMock()
    old = sys.modules.get("faster_whisper")
    sys.modules["faster_whisper"] = mock_whisper_module

    with (
        patch("stt.routes.transcribe.load_settings") as mock_load_settings,
        patch("stt.routes.transcribe.WhisperSTT") as mock_whisper_stt,
    ):
        mock_settings = MagicMock()
        mock_settings.stt.model_size = "tiny"
        mock_settings.stt.device = "cpu"
        mock_settings.stt.compute_type = "int8"
        mock_load_settings.return_value = mock_settings

        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = {
            "text": "hello world",
            "language": "en",
            "segments": [
                {"text": "hello world", "start": 0, "end": 1.2, "confidence": 0.98}
            ],
            "confidence": 0.98,
        }
        mock_whisper_stt.return_value = mock_instance

        from stt.main import app

        with TestClient(app) as client:
            yield client

    if old:
        sys.modules["faster_whisper"] = old
    else:
        del sys.modules["faster_whisper"]


class TestTranscribeRoute:
    def test_transcribe_returns_json(self, mock_stt_deps):
        wav_header = (
            b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>"
            b"\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        )
        audio_bytes = wav_header + b"\x00" * 16000
        response = mock_stt_deps.post(
            "/transcribe", content=audio_bytes, headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "hello world"
        assert data["language"] == "en"
        assert data["confidence"] == 0.98

    def test_transcribe_empty_body_returns_400(self, mock_stt_deps):
        response = mock_stt_deps.post(
            "/transcribe", content=b"", headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 400
        assert "No audio data" in response.json()["detail"]

    def test_transcribe_too_short_returns_400(self, mock_stt_deps):
        response = mock_stt_deps.post(
            "/transcribe", content=b"\x00" * 10, headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 400
