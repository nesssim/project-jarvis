from __future__ import annotations

import pathlib
import urllib.request
from dataclasses import dataclass
from enum import Enum

import numpy as np
from shared.logging import get_logger

logger = get_logger("stt.vad")

MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx"
MODEL_FILENAME = "silero_vad.onnx"
MODEL_DIR = pathlib.Path("/models/silero-vad")
DEFAULT_THRESHOLD = 0.5
DEFAULT_SILENCE_DURATION_MS = 800
SAMPLE_RATE = 16000
FRAME_SIZE = 512  # Silero VAD expects 512-sample frames at 16kHz


class VADError(Exception):
    """Raised when the VAD model fails to load or process audio."""


class VADEventType(str, Enum):
    SILENCE = "silence"
    SPEECH = "speech"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


@dataclass(frozen=True)
class VADEvent:
    type: VADEventType
    timestamp: float = 0.0
    probability: float = 0.0


class VADProcessor:
    """Silero VAD processor for speech endpointing.

    Processes 16kHz mono PCM audio chunks and detects speech/silence
    transitions. Emits SPEECH_START on first speech detection and
    SPEECH_END after a configurable silence duration.

    Configuration is loaded from settings.stt.vad.
    """

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        silence_duration_ms: int = DEFAULT_SILENCE_DURATION_MS,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        if threshold <= 0 or threshold > 1:
            raise VADError(f"VAD threshold must be in (0, 1], got {threshold}")
        if silence_duration_ms < 100:
            raise VADError(
                f"silence_duration_ms must be >= 100, got {silence_duration_ms}"
            )

        self.threshold = threshold
        self.silence_duration_ms = silence_duration_ms
        self.sample_rate = sample_rate

        self._model: object | None = None
        self._input_name: str | None = None
        self._sr_name: str | None = None

        self._is_speaking = False
        self._silence_samples = 0
        self._total_samples = 0
        self._speech_start_sample: int = 0
        self._frame_buffer: list[float] = []
        self._reset_internal_state()

    def _reset_internal_state(self) -> None:
        self._is_speaking = False
        self._silence_samples = 0
        self._speech_start_sample = 0
        self._frame_buffer = []
        self._h: list[np.ndarray] = []
        self._c: list[np.ndarray] = []
        self._last_probability = 0.0

    def reset(self) -> None:
        """Reset VAD state for a new utterance.

        Call this after each complete utterance (after SPEECH_END) to
        clear the internal state and start fresh.
        """
        self._reset_internal_state()
        logger.debug("vad reset")

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            import onnxruntime  # type: ignore[import-untyped]
        except ImportError as e:
            raise VADError(
                "onnxruntime not installed. "
                "Add 'onnxruntime>=1.15' to your dependencies."
            ) from e

        model_path = self._download_model()
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._model = onnxruntime.InferenceSession(str(model_path), opts)
        self._input_name = self._model.get_inputs()[0].name
        self._sr_name = self._model.get_inputs()[2].name
        logger.info("vad model loaded", path=str(model_path))

    def _download_model(self) -> pathlib.Path:
        model_path = MODEL_DIR / MODEL_FILENAME
        if model_path.exists():
            return model_path
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("downloading silero vad model", url=MODEL_URL)
        urllib.request.urlretrieve(MODEL_URL, model_path)
        logger.info("silero vad model downloaded", path=str(model_path))
        return model_path

    def _validate_audio(self, chunk: bytes) -> None:
        if not chunk:
            raise VADError("Empty audio chunk")
        if len(chunk) % 2 != 0:
            raise VADError(
                f"Audio chunk must have even byte length (16-bit PCM), "
                f"got {len(chunk)} bytes"
            )

    def process(self, chunk: bytes) -> VADEvent | None:
        """Process an audio chunk and return a VAD event if a state transition occurs.

        Args:
            chunk: Raw PCM 16-bit mono audio at 16kHz. Should be in
                   multiples of 512 samples (1024 bytes) for optimal
                   alignment, but any size is accepted.

        Returns:
            VADEvent if a transition occurred (SPEECH_START or SPEECH_END),
            or None if the state is unchanged (SILENCE or SPEECH continued).

        Raises:
            VADError: If the chunk is empty or invalid.

        """
        self._validate_audio(chunk)
        self._ensure_model()

        assert self._model is not None
        assert self._input_name is not None
        assert self._sr_name is not None

        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        samples = np.clip(samples, -1.0, 1.0)

        # Initialize LSTM state on first call
        if not self._h:
            self._h = [
                np.zeros((2, 1, 64), dtype=np.float32)
            ]
            self._c = [
                np.zeros((2, 1, 64), dtype=np.float32)
            ]

        sr = np.array(self.sample_rate, dtype=np.int64)

        # Process in FRAME_SIZE chunks
        offset = 0
        while offset < len(samples):
            frame = samples[offset : offset + FRAME_SIZE]
            if len(frame) < FRAME_SIZE:
                # Pad last frame if needed
                padded = np.zeros(FRAME_SIZE, dtype=np.float32)
                padded[: len(frame)] = frame
                frame = padded

            frame_input = frame.reshape(1, -1).astype(np.float32)
            prob, self._h[0], self._c[0] = self._model.run(
                ["output", "hn", "cn"],
                {
                    self._input_name: frame_input,
                    "hn": self._h[0],
                    "cn": self._c[0],
                    self._sr_name: sr,
                },
            )
            speech_prob = float(prob[0][0])
            self._last_probability = speech_prob
            self._total_samples += len(frame)
            offset += len(frame)

            is_speech = speech_prob >= self.threshold
            timestamp = self._total_samples / self.sample_rate

            if is_speech:
                self._silence_samples = 0
                if not self._is_speaking:
                    self._is_speaking = True
                    self._speech_start_sample = self._total_samples
                    logger.debug(
                        "vad speech start",
                        probability=round(speech_prob, 3),
                        timestamp=round(timestamp, 3),
                    )
                    return VADEvent(
                        type=VADEventType.SPEECH_START,
                        timestamp=timestamp,
                        probability=speech_prob,
                    )
            elif self._is_speaking:
                self._silence_samples += len(frame)
                silence_ms = (
                    self._silence_samples / self.sample_rate * 1000
                )
                if silence_ms >= self.silence_duration_ms:
                    self._is_speaking = False
                    logger.debug(
                        "vad speech end",
                        duration_ms=round(
                            (self._total_samples - self._speech_start_sample)
                            / self.sample_rate
                            * 1000
                        ),
                        silence_ms=round(silence_ms),
                        timestamp=round(timestamp, 3),
                    )
                    return VADEvent(
                        type=VADEventType.SPEECH_END,
                        timestamp=timestamp,
                        probability=speech_prob,
                    )

        return None

    @property
    def is_speaking(self) -> bool:
        """Whether speech is currently being detected."""
        return self._is_speaking

    @property
    def silence_ms(self) -> float:
        """Current silence duration in milliseconds (0 if speaking)."""
        if not self._is_speaking:
            return 0.0
        return self._silence_samples / self.sample_rate * 1000

    @property
    def last_probability(self) -> float:
        """Last speech probability output by the model."""
        return self._last_probability
