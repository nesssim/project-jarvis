from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from shared.logging import get_logger

logger = get_logger("orchestrator.voice")

router = APIRouter()


@router.post("/voice")
async def voice_pipeline(request: Request):
    stt_client = request.app.state.stt_client
    tts_client = request.app.state.tts_client
    llm_client = request.app.state.llm_client
    prompt_manager = request.app.state.prompt_manager

    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No audio data provided")

    logger.info("voice pipeline: transcribing", size=len(audio_bytes))
    transcription_result = await stt_client.transcribe(audio_bytes)
    text = transcription_result.get("text", "")

    if not text.strip():
        logger.info("voice pipeline: no speech detected")
        return Response(
            content=b"", media_type="audio/wav", headers={"X-Confidence": "0"}
        )

    confidence = transcription_result.get("confidence", 0)
    logger.info("voice pipeline: transcribed", text=text, confidence=confidence)

    system_prompt = prompt_manager.render(
        retrieved_memory="No relevant past conversations found.",
        short_term_buffer="No recent conversation history.",
    )

    llm_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]

    logger.info("voice pipeline: generating response")
    full_response = ""
    async for token in llm_client.generate(messages=llm_messages):
        full_response += token

    if not full_response.strip():
        full_response = "I'm sorry, I didn't understand that."

    logger.info("voice pipeline: synthesizing", response_len=len(full_response))
    audio_data = await tts_client.synthesize(full_response)

    return Response(
        content=audio_data,
        media_type="audio/wav",
        headers={
            "X-Confidence": str(confidence),
            "Content-Disposition": 'inline; filename="voice_response.wav"',
        },
    )
