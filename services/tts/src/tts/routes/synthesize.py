from __future__ import annotations

import io
import wave

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from shared.config import load_settings
from shared.logging import get_logger

from tts.piper_tts import PiperTTS, TTSInputError

logger = get_logger("tts.synthesize")

router = APIRouter()

_TTS_INSTANCE: PiperTTS | None = None

_DEFAULT_SAMPLE_RATE = 22050
_DEFAULT_CHANNELS = 1
_DEFAULT_SAMPLE_WIDTH = 2


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


def get_tts() -> PiperTTS:
    global _TTS_INSTANCE
    if _TTS_INSTANCE is None:
        _settings = load_settings()
        piper_cfg = _settings.tts.piper
        _TTS_INSTANCE = PiperTTS(
            model_path=piper_cfg.model_path,
            voice=piper_cfg.voice,
            sample_rate=piper_cfg.sample_rate,
        )
    return _TTS_INSTANCE


def _build_wav(audio_data: bytes, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_DEFAULT_CHANNELS)
        wf.setsampwidth(_DEFAULT_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)
    return buf.getvalue()


@router.post("/synthesize")
async def synthesize(body: SynthesizeRequest):
    tts = get_tts()
    try:
        chunks = list(tts.synthesize(body.text))
    except TTSInputError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not chunks:
        raise HTTPException(status_code=500, detail="TTS produced no audio")

    audio_data = b"".join(chunks)
    wav_bytes = _build_wav(audio_data, sample_rate=_DEFAULT_SAMPLE_RATE)

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="speech.wav"'},
    )
