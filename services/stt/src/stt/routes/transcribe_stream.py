from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from shared.config import load_settings
from shared.logging import get_logger

from stt.vad import VADError, VADEventType, VADProcessor
from stt.whisper_stt import WhisperSTT

logger = get_logger("stt.transcribe_stream")

router = APIRouter()

_WHISPER_INSTANCE: WhisperSTT | None = None

PARTIAL_INTERVAL_MS = 500  # Emit partial transcript every 500ms of audio
VAD_CHECK_INTERVAL_MS = 100  # Check VAD every 100ms
SAMPLE_RATE = 16000
FRAME_MS = 100  # 100ms frames = 1600 samples at 16kHz
FRAME_BYTES = FRAME_MS * SAMPLE_RATE * 2 // 1000  # 3200 bytes


def _get_whisper() -> WhisperSTT:
    global _WHISPER_INSTANCE
    if _WHISPER_INSTANCE is None:
        settings = load_settings()
        stt_cfg = settings.stt
        _WHISPER_INSTANCE = WhisperSTT(
            model_size=stt_cfg.whisper.model_size,
            device=stt_cfg.whisper.device,
            compute_type=stt_cfg.whisper.compute_type,
        )
    return _WHISPER_INSTANCE


def _create_vad() -> VADProcessor:
    settings = load_settings()
    vad_cfg = settings.stt.vad
    return VADProcessor(
        threshold=vad_cfg.threshold, silence_duration_ms=vad_cfg.silence_duration_ms
    )


def _parse_audio_params(request: Request) -> tuple[int, int, int]:
    """Parse audio parameters from query string, defaulting to 16kHz mono 16-bit."""
    sample_rate = int(request.query_params.get("sample_rate", SAMPLE_RATE))
    channels = int(request.query_params.get("channels", 1))
    sample_width = int(request.query_params.get("sample_width", 2))
    return sample_rate, channels, sample_width


async def _receive_audio_chunks(request: Request) -> AsyncIterator[bytes]:
    """Receive raw PCM audio chunks from the request body stream.

    Yields 100ms frames of audio data.
    """
    buffer = bytearray()
    frame_target = FRAME_BYTES

    async for chunk in request.stream():
        buffer.extend(chunk)
        while len(buffer) >= frame_target:
            yield bytes(buffer[:frame_target])
            del buffer[:frame_target]

    # Yield remaining bytes
    if buffer:
        yield bytes(buffer)


def _resample_to_16k(
    chunk: bytes, sample_rate: int, channels: int, sample_width: int
) -> bytes:
    """Resample multi-channel/non-16k audio to 16kHz mono.

    Only handles the simple cases:
    - 16kHz mono: passthrough
    - 16kHz stereo: average channels
    - 8kHz mono: simple upsampling (repeat each sample)
    - 44.1kHz mono: simple downsampling (skip samples)
    """
    import numpy as np  # type: ignore[import-untyped]

    if sample_rate == SAMPLE_RATE and channels == 1 and sample_width == 2:
        return chunk  # Already in correct format

    samples = np.frombuffer(chunk, dtype=np.int16)

    # Convert to mono if stereo
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)

    # Resample to 16kHz
    if sample_rate != SAMPLE_RATE:
        ratio = SAMPLE_RATE / sample_rate
        target_len = int(len(samples) * ratio)
        indices = np.linspace(0, len(samples) - 1, target_len)
        samples = np.interp(
            indices, np.arange(len(samples)), samples.astype(np.float32)
        ).astype(np.int16)

    return samples.tobytes()


def _make_sse(event: str, data: dict) -> str:
    """Build a Server-Sent Events formatted string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/transcribe-stream")
async def transcribe_stream(request: Request):
    """Streaming speech-to-text endpoint with built-in VAD endpointing.

    Accepts a stream of raw PCM audio bytes (chunked transfer encoding)
    and returns a Server-Sent Events stream with the following events:

      event: vad.speech_start
      data: {"timestamp": 0.5}

      event: transcript.partial
      data: {"text": "hello world", "confidence": 0.5, "timestamp": 2.0}

      event: vad.speech_end
      data: {"silence_duration_ms": 800, "utterance_duration_ms": 3200}

      event: transcript.final
      data: {"text": "hello world", "confidence": 0.92, "language": "en"}

      event: error
      data: {"message": "..."}

    Query parameters:
      - sample_rate (int, default 16000): Input audio sample rate
      - channels (int, default 1): Number of audio channels
      - sample_width (int, default 2): Bytes per sample

    The endpoint buffers audio until VAD detects end-of-speech,
    then returns the final transcription. Partial transcripts are
    emitted periodically during speech.
    """
    sample_rate, channels, sample_width = _parse_audio_params(request)

    stt = _get_whisper()
    vad = _create_vad()

    audio_buffer = bytearray()
    last_partial_time = 0.0
    utterance_active = False
    partial_counter = 0

    async def event_stream() -> AsyncIterator[str]:
        nonlocal audio_buffer, last_partial_time, utterance_active, partial_counter

        try:
            async for frame in _receive_audio_chunks(request):
                # Resample to 16kHz mono if needed
                pcm_frame = _resample_to_16k(frame, sample_rate, channels, sample_width)

                # Add to buffer
                audio_buffer.extend(pcm_frame)

                # Process VAD
                try:
                    event = vad.process(pcm_frame)
                except VADError as e:
                    yield _make_sse("error", {"message": str(e)})
                    return

                now = time.time()

                if event is not None:
                    if event.type == VADEventType.SPEECH_START:
                        utterance_active = True
                        yield _make_sse(
                            "vad.speech_start", {"timestamp": event.timestamp}
                        )
                        logger.debug("vad speech start", timestamp=event.timestamp)

                    elif event.type == VADEventType.SPEECH_END:
                        end_payload = {
                            "silence_duration_ms": vad.silence_duration_ms,
                            "utterance_duration_ms": round(event.timestamp * 1000),
                        }
                        yield _make_sse("vad.speech_end", end_payload)
                        logger.debug(
                            "vad speech end, transcribing final",
                            buffer_bytes=len(audio_buffer),
                        )

                        # Transcribe final
                        try:
                            result = stt.transcribe(bytes(audio_buffer))
                            final_text = result.get("text", "").strip()
                            if final_text:
                                yield _make_sse(
                                    "transcript.final",
                                    {
                                        "text": final_text,
                                        "confidence": result.get("confidence", 0.0),
                                        "language": result.get("language", "en"),
                                    },
                                )
                        except Exception as e:
                            yield _make_sse(
                                "error",
                                {"message": (f"Final transcription failed: {e}")},
                            )
                            return
                        finally:
                            audio_buffer = bytearray()
                            utterance_active = False
                            partial_counter = 0
                            vad.reset()

                # Emit partials during active speech
                if utterance_active and (now - last_partial_time) >= (
                    PARTIAL_INTERVAL_MS / 1000
                ):
                    last_partial_time = now
                    partial_counter += 1

                    # Only emit partials every ~3 iterations to reduce load
                    if partial_counter % 3 == 0 and len(audio_buffer) >= 160:
                        try:
                            partial_result = stt.transcribe(bytes(audio_buffer))
                            partial_text = partial_result.get("text", "").strip()
                            if partial_text:
                                yield _make_sse(
                                    "transcript.partial",
                                    {
                                        "text": partial_text,
                                        "confidence": partial_result.get(
                                            "confidence", 0.0
                                        ),
                                    },
                                )
                        except Exception as e:
                            logger.warning(
                                "partial transcription failed",
                                error=str(e),
                                buffer_bytes=len(audio_buffer),
                            )

            # Stream ended — if audio remains, transcribe it
            if audio_buffer and len(audio_buffer) >= 160:
                logger.debug(
                    "stream ended, transcribing remaining audio",
                    buffer_bytes=len(audio_buffer),
                )
                try:
                    result = stt.transcribe(bytes(audio_buffer))
                    final_text = result.get("text", "").strip()
                    if final_text:
                        yield _make_sse(
                            "transcript.final",
                            {
                                "text": final_text,
                                "confidence": result.get("confidence", 0.0),
                                "language": result.get("language", "en"),
                            },
                        )
                except Exception as e:
                    yield _make_sse(
                        "error", {"message": f"Final transcription failed: {e}"}
                    )

        except Exception as e:
            logger.exception("transcribe stream error")
            yield _make_sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
