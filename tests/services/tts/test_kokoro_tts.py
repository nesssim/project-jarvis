from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from tts.kokoro_tts import KokoroTTS, TTSInputError


@pytest.fixture(autouse=True)
def mock_kokoro():
    mod = types.ModuleType("kokoro")
    mod.KokoroPipeline = MagicMock()

    old = sys.modules.get("kokoro")
    sys.modules["kokoro"] = mod
    yield mod
    if old:
        sys.modules["kokoro"] = old
    else:
        del sys.modules["kokoro"]


class TestKokoroTTS:
    def test_synthesize_returns_audio_chunks(self, mock_kokoro):
        mock_pipeline = MagicMock()
        mock_kokoro.KokoroPipeline.return_value = mock_pipeline

        mock_chunk = MagicMock()
        mock_chunk.audio = b"\x00" * 16000
        mock_pipeline.return_value = iter([mock_chunk])

        tts = KokoroTTS(voice="af_heart")
        chunks = list(tts.synthesize("Hello world"))

        assert len(chunks) > 0
        assert isinstance(chunks[0], bytes)

    def test_empty_text_raises(self, mock_kokoro):
        tts = KokoroTTS(voice="af_heart")
        with pytest.raises(TTSInputError, match="Text cannot be empty"):
            list(tts.synthesize(""))

    def test_whitespace_only_raises(self, mock_kokoro):
        tts = KokoroTTS(voice="af_heart")
        with pytest.raises(TTSInputError):
            list(tts.synthesize("   "))

    def test_voice_configurable(self, mock_kokoro):
        mock_pipeline = MagicMock()
        mock_kokoro.KokoroPipeline.return_value = mock_pipeline

        tts = KokoroTTS(voice="am_michael")
        assert tts.voice == "am_michael"

    def test_voice_applied_to_pipeline(self, mock_kokoro):
        mock_pipeline = MagicMock()
        mock_kokoro.KokoroPipeline.return_value = mock_pipeline
        mock_pipeline.return_value = iter([])

        tts = KokoroTTS(voice="af_bella")
        tts.synthesize("Test")
        mock_kokoro.KokoroPipeline.assert_called_once()
