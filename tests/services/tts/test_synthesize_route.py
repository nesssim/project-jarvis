from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_tts_deps():
    mock_piper_mod = types.ModuleType("piper")
    mock_piper_mod.PiperVoice = MagicMock()
    mock_piper_download = types.ModuleType("piper.download")
    mock_piper_download.Voice = MagicMock()
    sys.modules["piper"] = mock_piper_mod
    sys.modules["piper.download"] = mock_piper_download

    with (
        patch("tts.routes.synthesize.load_settings") as mock_load_settings,
        patch("tts.routes.synthesize.PiperTTS") as mock_piper_tts,
    ):
        mock_settings = MagicMock()
        mock_settings.tts.model_path = "/fake/model.pt"
        mock_settings.tts.voice = "default"
        mock_settings.tts.sample_rate = 22050
        mock_load_settings.return_value = mock_settings

        mock_instance = MagicMock()
        mock_instance.synthesize.return_value = [b"\x00" * 16000]
        mock_piper_tts.return_value = mock_instance

        from tts.main import app

        with TestClient(app) as client:
            yield client


class TestSynthesizeRoute:
    def test_synthesize_returns_wav(self, mock_tts_deps):
        response = mock_tts_deps.post("/synthesize", json={"text": "Hello world"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert len(response.content) > 44
        assert response.content[:4] == b"RIFF"

    def test_synthesize_empty_text_returns_422(self, mock_tts_deps):
        response = mock_tts_deps.post("/synthesize", json={"text": ""})
        assert response.status_code == 422

    def test_synthesize_missing_text_returns_422(self, mock_tts_deps):
        response = mock_tts_deps.post("/synthesize", json={})
        assert response.status_code == 422
