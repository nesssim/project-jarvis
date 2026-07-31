from __future__ import annotations

import pathlib
import urllib.request
from typing import Any

from shared.logging import get_logger

logger = get_logger("orchestrator.wake_word")

MODEL_URL = "https://github.com/dscripka/openWakeWord/raw/main/openwakeword/resources/models/hey_jarvis_v0.1.onnx"
MODEL_FILENAME = "hey_jarvis_v0.1.onnx"
MODEL_DIR = pathlib.Path("/models/wake-word")


class WakeWordDetector:
    """openWakeWord-based wake word detector.

    Listens for a configurable wake word (default: "hey jarvis")
    on 16kHz mono PCM audio chunks.
    """

    def __init__(
        self,
        model_path: str = str(MODEL_DIR / MODEL_FILENAME),
        sensitivity: float = 0.5,
    ) -> None:
        self._sensitivity = sensitivity
        self._model: Any = None
        self._model_path = pathlib.Path(model_path)

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            import openwakeword
        except ImportError:
            raise ImportError(
                "openWakeWord not installed. "
                "Add 'openwakeword>=0.4.0' to your dependencies."
            ) from None

        if not self._model_path.exists():
            self._download_model()

        self._model = openwakeword.Model(wakeword_models=[str(self._model_path)])
        logger.info("wake word model loaded", path=str(self._model_path))

    def _download_model(self) -> None:
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("downloading wake word model", url=MODEL_URL)
        urllib.request.urlretrieve(MODEL_URL, self._model_path)
        logger.info("wake word model downloaded", path=str(self._model_path))

    def detect(self, audio_chunk: bytes) -> bool:
        """Check if the wake word is detected in the audio chunk.

        Args:
            audio_chunk: Raw PCM 16-bit mono audio at 16kHz

        Returns:
            True if wake word detected above sensitivity threshold

        """
        import numpy as np

        self._ensure_model()

        samples = (
            np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        )
        prediction = self._model.predict(samples)

        max_score = max(prediction.values()) if prediction else 0.0
        return max_score >= self._sensitivity

    def reset(self) -> None:
        """Reset the internal state."""
        if self._model is not None:
            self._model.reset()
