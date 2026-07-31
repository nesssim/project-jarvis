from __future__ import annotations

from typing import Any


class STTModelError(Exception):
    """Raised when the STT model fails to load or process audio."""


class WhisperSTT:
    _instances: dict[str, WhisperSTT] = {}

    def __new__(
        cls,
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> WhisperSTT:
        key = f"{model_size}:{device}:{compute_type}"
        if key not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        if getattr(self, "_initialized", False):
            return
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._initialized = True

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            import faster_whisper  # type: ignore[import-untyped]

            self._model = faster_whisper.WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        except OSError as e:
            raise STTModelError(
                f"Failed to load Whisper model '{self._model_size}': {e}"
            ) from e

    def transcribe(
        self, audio_bytes: bytes, language: str | None = None
    ) -> dict[str, Any]:
        if not audio_bytes or len(audio_bytes) < 160:
            return {"text": "", "language": language or "en", "segments": [], "confidence": 0.0}

        self._load_model()
        assert self._model is not None

        import io
        import wave

        if audio_bytes[:4] == b"RIFF":
            wav_buffer = io.BytesIO(audio_bytes)
        else:
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)
            wav_buffer.seek(0)

        segments, info = self._model.transcribe(
            wav_buffer,
            language=language,
            beam_size=5,
        )

        result_segments = []
        total_prob = 0.0
        seg_count = 0
        for seg in segments:
            result_segments.append({
                "text": seg.text,
                "start": seg.start,
                "end": seg.end,
                "probability": seg.probability,
            })
            total_prob += seg.probability
            seg_count += 1

        transcript = " ".join(s["text"] for s in result_segments)
        return {
            "text": transcript.strip(),
            "language": info.language,
            "segments": result_segments,
            "confidence": total_prob / seg_count if seg_count > 0 else 0.0,
        }
