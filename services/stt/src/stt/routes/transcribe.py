from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from shared.audio import InvalidWAVError, parse_wav_header
from shared.config import load_settings
from shared.logging import get_logger

from stt.whisper_stt import WhisperSTT

logger = get_logger("stt.transcribe")

router = APIRouter()

_WHISPER_INSTANCE: WhisperSTT | None = None


def get_whisper_stt() -> WhisperSTT:
    global _WHISPER_INSTANCE
    if _WHISPER_INSTANCE is None:
        _settings = load_settings()
        stt_cfg = _settings.stt
        _WHISPER_INSTANCE = WhisperSTT(
            model_size=stt_cfg.model_size,
            device=stt_cfg.device,
            compute_type=stt_cfg.compute_type,
        )
    return _WHISPER_INSTANCE


@router.post("/transcribe")
async def transcribe(request: Request):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="No audio data provided")

    if len(body) < 44:
        raise HTTPException(status_code=400, detail="Audio too short to be valid WAV")

    try:
        fmt = parse_wav_header(body)
    except InvalidWAVError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    stt = get_whisper_stt()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, stt.transcribe, body)

    return {
        "text": result["text"],
        "language": result["language"],
        "segments": result["segments"],
        "confidence": result["confidence"],
        "format": {
            "sample_rate": fmt.sample_rate,
            "channels": fmt.channels,
            "sample_width": fmt.byte_width,
        },
    }
