from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from tts.piper_tts import PiperTTS, TTSInputError


@pytest.fixture(autouse=True)
def mock_piper_modules():
    piper_mod = types.ModuleType("piper")
    piper_download_mod = types.ModuleType("piper.download")

    mock_piper_voice = MagicMock()
    piper_mod.PiperVoice = mock_piper_voice

    mock_voice = MagicMock()
    piper_download_mod.Voice = mock_voice

    old_piper = sys.modules.get("piper")
    old_download = sys.modules.get("piper.download")
    sys.modules["piper"] = piper_mod
    sys.modules["piper.download"] = piper_download_mod
    yield {"PiperVoice": mock_piper_voice, "Voice": mock_voice}
    if old_piper:
        sys.modules["piper"] = old_piper
    else:
        del sys.modules["piper"]
    if old_download:
        sys.modules["piper.download"] = old_download
    else:
        del sys.modules["piper.download"]


class TestPiperTTS:
    def test_synthesize_returns_audio_chunks(self, mock_piper_modules):
        mock_voice = mock_piper_modules["Voice"]
        mock_piper_voice = mock_piper_modules["PiperVoice"]

        voice_instance = MagicMock()
        mock_voice.return_value = voice_instance

        piper_voice_instance = MagicMock()
        piper_voice_instance.synthesize.return_value = (b"\x00" * 16000, 22050)
        mock_piper_voice.return_value = piper_voice_instance

        tts = PiperTTS(model_path="/fake/model.pt", voice="default")
        chunks = list(tts.synthesize("Hello world"))

        assert len(chunks) > 0
        assert isinstance(chunks[0], bytes)
        assert len(chunks[0]) > 0

    def test_synthesize_chunks_are_valid_audio(self, mock_piper_modules):
        mock_voice = mock_piper_modules["Voice"]
        mock_piper_voice = mock_piper_modules["PiperVoice"]

        voice_instance = MagicMock()
        mock_voice.return_value = voice_instance

        piper_voice_instance = MagicMock()
        mock_wav = b"\x00" * 16000
        piper_voice_instance.synthesize.return_value = (mock_wav, 22050)
        mock_piper_voice.return_value = piper_voice_instance

        tts = PiperTTS(model_path="/fake/model.pt", voice="default")
        chunks = list(tts.synthesize("Hello world"))
        assert chunks[0] == mock_wav

    def test_empty_text_raises_error(self, mock_piper_modules):
        tts = PiperTTS(model_path="/fake/model.pt", voice="default")
        with pytest.raises(TTSInputError, match="Text cannot be empty"):
            list(tts.synthesize(""))

    def test_whitespace_only_raises_error(self, mock_piper_modules):
        tts = PiperTTS(model_path="/fake/model.pt", voice="default")
        with pytest.raises(TTSInputError):
            list(tts.synthesize("   \n  \t  "))

    def test_long_text_chunked_correctly(self, mock_piper_modules):
        mock_voice = mock_piper_modules["Voice"]
        mock_piper_voice = mock_piper_modules["PiperVoice"]

        voice_instance = MagicMock()
        mock_voice.return_value = voice_instance

        piper_voice_instance = MagicMock()
        piper_voice_instance.synthesize.return_value = (b"\x00" * 8000, 22050)
        mock_piper_voice.return_value = piper_voice_instance

        long_text = "Hello. " * 50

        tts = PiperTTS(model_path="/fake/model.pt", voice="default")
        chunks = list(tts.synthesize(long_text))
        assert len(chunks) > 0
        assert sum(len(c) for c in chunks) > 0

    def test_model_not_found_raises_error(self, mock_piper_modules):
        mock_voice = mock_piper_modules["Voice"]
        mock_voice.side_effect = Exception("Model not found")

        with pytest.raises(Exception, match="Model not found"):
            PiperTTS(model_path="/nonexistent/model.pt", voice="default")

    def test_sample_rate_configurable(self, mock_piper_modules):
        mock_voice = mock_piper_modules["Voice"]
        mock_piper_voice = mock_piper_modules["PiperVoice"]

        voice_instance = MagicMock()
        mock_voice.return_value = voice_instance

        piper_voice_instance = MagicMock()
        piper_voice_instance.synthesize.return_value = (b"\x00" * 16000, 44100)
        mock_piper_voice.return_value = piper_voice_instance

        tts = PiperTTS(model_path="/fake/model.pt", voice="default", sample_rate=44100)
        chunks = list(tts.synthesize("Test"))
        assert len(chunks) > 0
