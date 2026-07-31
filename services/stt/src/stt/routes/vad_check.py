from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from shared.audio import parse_wav_header
from shared.config import load_settings
from shared.logging import get_logger

from stt.vad import VADError, VADProcessor

logger = get_logger("stt.vad_check")

router = APIRouter()

_VAD_INSTANCES: dict[str, tuple[VADProcessor, float]] = {}
_VAD_TTL_SECONDS = 300


def _evict_stale_vad() -> None:
    now = time.monotonic()
    stale = [
        key for key, (_, ts) in _VAD_INSTANCES.items() if now - ts > _VAD_TTL_SECONDS
    ]
    for key in stale:
        logger.debug("evicting stale vad instance", session_id=key)
        del _VAD_INSTANCES[key]


SAMPLE_RATE = 16000


class VADResponse(BaseModel):
    is_speech: bool
    probability: float
    silence_duration_ms: float
    utterance_duration_ms: float


def _get_vad(session_id: str | None = None) -> VADProcessor:
    global _VAD_INSTANCES
    _evict_stale_vad()

    settings = load_settings()
    vad_cfg = settings.stt.vad
    max_instances = vad_cfg.max_instances

    key: str = session_id if session_id is not None else "_default"
    if key not in _VAD_INSTANCES:
        if len(_VAD_INSTANCES) >= max_instances:
            raise VADError("Maximum VAD sessions reached")
        _VAD_INSTANCES[key] = (
            VADProcessor(
                threshold=vad_cfg.threshold,
                silence_duration_ms=vad_cfg.silence_duration_ms,
            ),
            time.monotonic(),
        )
    else:
        # Update timestamp to prevent eviction
        proc, _ = _VAD_INSTANCES[key]
        _VAD_INSTANCES[key] = (proc, time.monotonic())
    return _VAD_INSTANCES[key][0]


@router.post("/vad", response_model=VADResponse)
async def check_vad(request: Request, session_id: str | None = None):
    """Check if the given audio chunk contains speech.

    Accepts raw PCM 16-bit mono audio at 16kHz (or WAV) in the request
    body. Returns whether speech is detected and the current VAD state.

    VAD state is maintained per session_id. If no session_id is provided,
    a default shared instance is used (not suitable for concurrent access).
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="No audio data provided")

    if len(body) < 160:
        return VADResponse(
            is_speech=False,
            probability=0.0,
            silence_duration_ms=0.0,
            utterance_duration_ms=0.0,
        )
    try:
        vad = _get_vad(session_id)
    except VADError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Strip WAV header if present
    audio_data = body
    if body[:4] == b"RIFF":
        try:
            parse_wav_header(body)
            offset = 12
            while offset + 8 <= len(body):
                chunk_id = body[offset : offset + 4]
                chunk_size = int.from_bytes(body[offset + 4 : offset + 8], "little")
                if chunk_id == b"data":
                    audio_data = body[offset + 8 : offset + 8 + chunk_size]
                    break
                offset += 8 + chunk_size
                if chunk_size % 2 != 0:
                    offset += 1
        except Exception:
            audio_data = body

    try:
        event = vad.process(audio_data)
    except VADError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return VADResponse(
        is_speech=vad.is_speaking
        or (event is not None and event.type.value in ("speech_start", "speech")),
        probability=vad.last_probability,
        silence_duration_ms=vad.silence_ms,
        utterance_duration_ms=0.0,
    )


@router.post("/vad/reset")
async def reset_vad(session_id: str | None = None):
    """Reset the VAD processor state for the given session.

    If session_id is provided, only that session's VAD is reset.
    Otherwise, the default instance is reset.
    """
    try:
        vad = _get_vad(session_id)
    except VADError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    vad.reset()
    # Update timestamp on reset
    key: str = session_id if session_id is not None else "_default"
    if key in _VAD_INSTANCES:
        proc, _ = _VAD_INSTANCES[key]
        _VAD_INSTANCES[key] = (proc, time.monotonic())
    logger.debug(
        "vad reset via api", session_id=session_id, active_instances=len(_VAD_INSTANCES)
    )
    return {"status": "ok"}
