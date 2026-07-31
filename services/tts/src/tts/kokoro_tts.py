from __future__ import annotations

import sys
from collections.abc import Iterator


class TTSInputError(Exception):
    """Raised when TTS input is invalid."""


def _import_kokoro():
    if "kokoro" not in sys.modules:
        import kokoro  # noqa: F401
    return sys.modules["kokoro"]


class KokoroTTS:
    def __init__(self, voice: str = "af_heart") -> None:
        self._voice = voice
        self._pipeline = None
        self._load_pipeline()

    def _load_pipeline(self) -> None:
        kokoro_mod = _import_kokoro()
        self._pipeline = kokoro_mod.KokoroPipeline(
            model="kokoro-v0_19.pth",
            voice=self._voice,
        )

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(self, text: str) -> Iterator[bytes]:
        if not text or not text.strip():
            raise TTSInputError("Text cannot be empty")

        assert self._pipeline is not None

        for chunk in self._pipeline(text):
            yield chunk.audio
