from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from stt.whisper_stt import STTModelError, WhisperSTT


def _make_segment(text: str, start: float = 0.0, end: float = 1.0, probability: float = 0.95):
    seg = MagicMock()
    seg.text = text
    seg.start = start
    seg.end = end
    seg.probability = probability
    return seg


@pytest.fixture(autouse=True)
def reset_whisper_singleton():
    WhisperSTT._instances.clear()


@pytest.fixture
def mock_faster_whisper():
    mock_module = types.ModuleType("faster_whisper")
    mock_module.WhisperModel = MagicMock()
    old = sys.modules.get("faster_whisper")
    sys.modules["faster_whisper"] = mock_module
    yield mock_module
    if old:
        sys.modules["faster_whisper"] = old
    else:
        del sys.modules["faster_whisper"]


class TestWhisperSTT:
    def test_transcribe_returns_text(self, mock_faster_whisper):
        seg = _make_segment("hello world", 0.0, 1.2, 0.98)
        info_mock = MagicMock()
        info_mock.language = "en"
        model_instance = MagicMock()
        model_instance.transcribe.return_value = ([seg], info_mock)
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"\x00" * 16000)
        assert result["text"] == "hello world"
        assert result["language"] == "en"

    def test_model_loaded_once_lazy(self, mock_faster_whisper):
        info_mock = MagicMock()
        info_mock.language = "en"
        model_instance = MagicMock()
        model_instance.transcribe.return_value = ([], info_mock)
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt1 = WhisperSTT(model_size="tiny", device="cpu")
        stt1.transcribe(b"\x00" * 16000)
        stt2 = WhisperSTT(model_size="tiny", device="cpu")
        stt2.transcribe(b"\x00" * 16000)
        assert mock_faster_whisper.WhisperModel.call_count == 1

    def test_empty_audio_returns_empty(self, mock_faster_whisper):
        model_instance = MagicMock()
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"")
        assert result["text"] == ""

    def test_very_short_audio_handled(self, mock_faster_whisper):
        model_instance = MagicMock()
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"\x00" * 80)
        assert result["text"] == ""

    def test_different_languages(self, mock_faster_whisper):
        seg = _make_segment("hola mundo", 0.0, 1.0, 0.97)
        info_mock = MagicMock()
        info_mock.language = "es"
        model_instance = MagicMock()
        model_instance.transcribe.return_value = ([seg], info_mock)
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"\x00" * 16000, language="es")
        assert result["language"] == "es"
        assert result["text"] == "hola mundo"

    def test_gpu_device_selection(self, mock_faster_whisper):
        model_instance = MagicMock()
        model_instance.transcribe.return_value = ([], MagicMock(language="en"))
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="small", device="cuda", compute_type="float16")
        stt.transcribe(b"\x00" * 16000)
        mock_faster_whisper.WhisperModel.assert_called_once_with(
            "small", device="cuda", compute_type="float16"
        )

    def test_model_not_found_raises(self, mock_faster_whisper):
        mock_faster_whisper.WhisperModel.side_effect = OSError("Model not found")
        stt = WhisperSTT(model_size="nonexistent", device="cpu")
        with pytest.raises(STTModelError, match="Model not found"):
            stt.transcribe(b"\x00" * 16000)

    def test_segments_in_result(self, mock_faster_whisper):
        segments = [
            _make_segment("hello", 0.0, 0.5, 0.98),
            _make_segment("world", 0.6, 1.2, 0.95),
        ]
        info_mock = MagicMock()
        info_mock.language = "en"
        model_instance = MagicMock()
        model_instance.transcribe.return_value = (segments, info_mock)
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"\x00" * 16000)
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "hello"
        assert result["segments"][1]["text"] == "world"

    def test_confidence_in_result(self, mock_faster_whisper):
        seg = _make_segment("hello", 0.0, 0.5, 0.98)
        info_mock = MagicMock()
        info_mock.language = "en"
        model_instance = MagicMock()
        model_instance.transcribe.return_value = ([seg], info_mock)
        mock_faster_whisper.WhisperModel.return_value = model_instance

        stt = WhisperSTT(model_size="tiny", device="cpu")
        result = stt.transcribe(b"\x00" * 16000)
        assert result["confidence"] == 0.98
