from __future__ import annotations

import sys
from collections.abc import Iterator


class TTSInputError(Exception):
    """Raised when TTS input is invalid."""


def _import_piper():
    if "piper" not in sys.modules:
        import piper  # noqa: F401
    return sys.modules["piper"]


def _import_piper_download():
    if "piper.download" not in sys.modules:
        import piper.download  # noqa: F401
    return sys.modules["piper.download"]


class PiperTTS:
    def __init__(
        self,
        model_path: str,
        voice: str = "default",
        sample_rate: int = 22050,
    ) -> None:
        self._model_path = model_path
        self._voice = voice
        self._sample_rate = sample_rate
        self._voice_obj = None
        self._load_voice()

    def _load_voice(self) -> None:
        piper_mod = _import_piper()
        download_mod = _import_piper_download()
        PiperVoice = piper_mod.PiperVoice  # noqa: N806
        Voice = download_mod.Voice  # noqa: N806

        voice = Voice(model_path=self._model_path, voice_name=self._voice)
        self._voice_obj = PiperVoice(voice)

    def _chunk_text(self, text: str, max_chars: int = 500) -> list[str]:
        sentences = text.replace("\n", " ").split(". ")
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current}{sentence}. " if current else f"{sentence}. "
            if len(candidate) > max_chars and current:
                chunks.append(current.strip())
                current = f"{sentence}. "
            else:
                current = candidate
        if current:
            chunks.append(current.strip())
        return chunks or [""]

    def synthesize(self, text: str) -> Iterator[bytes]:
        if not text or not text.strip():
            raise TTSInputError("Text cannot be empty")

        assert self._voice_obj is not None

        chunks = self._chunk_text(text)
        for chunk in chunks:
            audio_bytes, _ = self._voice_obj.synthesize(
                chunk,
                length_scale=1.0,
            )
            yield audio_bytes
