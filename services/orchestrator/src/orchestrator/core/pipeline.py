from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.config import Settings
from shared.logging import get_logger
from shared.messages import MessageType
from shared.state import AUDIO_INPUT_STATES, FSMState
from tts.chunker import SentenceChunker

from orchestrator.clients.llm import BaseLLMClient
from orchestrator.clients.stt_client import STTClient
from orchestrator.clients.tts_client import TTSClient
from orchestrator.core.prompt import PromptManager
from orchestrator.core.state_machine import StateMachine

logger = get_logger("orchestrator.pipeline")


class PipelineError(Exception):
    """Base exception for pipeline failures."""


class STTError(PipelineError):
    """Raised when speech-to-text fails."""


class TTSError(PipelineError):
    """Raised when text-to-speech fails."""


class LLMError(PipelineError):
    """Raised when the LLM fails to generate a response."""


@dataclass
class PipelineResult:
    """Result of running the full streaming pipeline."""

    transcript: str = ""
    response_text: str = ""
    audio_bytes: bytes = b""
    error: str | None = None


@dataclass
class PartialTranscript:
    """A partial transcript emitted during speech."""

    text: str
    confidence: float
    is_final: bool


@dataclass
class AudioChunk:
    """A chunk of TTS audio."""

    data: bytes
    is_final: bool = False


def _extract_pcm_from_wav(wav_bytes: bytes) -> bytes:
    """Extract raw PCM data from a WAV file."""
    if wav_bytes[:4] != b"RIFF":
        return wav_bytes

    pos = 12
    while pos + 8 <= len(wav_bytes):
        chunk_id = wav_bytes[pos : pos + 4]
        chunk_size = int.from_bytes(
            wav_bytes[pos + 4 : pos + 8], "little"
        )
        if chunk_id == b"data":
            return wav_bytes[pos + 8 : pos + 8 + chunk_size]
        pos += 8 + chunk_size
        if chunk_size % 2 != 0:
            pos += 1
    return wav_bytes


class RealtimePipeline:
    """FSM-driven concurrent voice pipeline.

    Architecture:
    - Owns a StateMachine instance
    - Accepts audio chunks via push_audio()
    - On speech_end, launches concurrent STT/LLM/TTS tasks via TaskGroup
    - Sentence-chunks LLM output and sends to TTS incrementally
    - Emits events (transcript, token, audio) via event callback
    - Supports barge-in: stops TTS, re-enters LISTENING
    """

    def __init__(
        self,
        stt_client: STTClient,
        tts_client: TTSClient,
        llm_client: BaseLLMClient,
        prompt_manager: PromptManager,
        settings: Settings,
        event_callback: Callable[[str, dict], Any] | None = None,
    ) -> None:
        self._stt = stt_client
        self._tts = tts_client
        self._llm = llm_client
        self._prompt_manager = prompt_manager
        self._settings = settings
        self._event_callback = event_callback

        self._fsm = StateMachine(on_transition=self._on_fsm_transition)
        self._audio_buffer = bytearray()
        self._session_id = ""
        self._cancel_event = asyncio.Event()
        self._tts_output_queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue()
        self._tts_task: asyncio.Task | None = None
        self._barge_in_monitor_task: asyncio.Task | None = None

    @property
    def fsm(self) -> StateMachine:
        return self._fsm

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id

    def reset_buffer(self) -> None:
        self._audio_buffer = bytearray()

    async def push_audio(self, chunk: bytes) -> bool:
        if self._fsm.state not in AUDIO_INPUT_STATES:
            return False
        self._audio_buffer.extend(chunk)
        return True

    async def handle_speech_end(self) -> None:
        await self._emit(MessageType.TRANSCRIPT_FINAL.value, {
            "text": "...", "confidence": 0.0,
        })

        await self._fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")

        audio_data = bytes(self._audio_buffer)
        self._audio_buffer.clear()

        try:
            stt_result = await self._run_stt(audio_data)
        except STTError:
            return

        if self._cancel_event.is_set():
            return

        self._tts_task = asyncio.create_task(
            self._run_llm_and_tts(stt_result.get("text", ""))
        )

    async def handle_barge_in(self) -> None:
        self._cancel_event.set()

        await self._fsm.transition(FSMState.INTERRUPTED, reason="barge_in")

        jitter_ms = self._settings.listening.barge_in_jitter_ms
        if self._tts_task and not self._tts_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._tts_task),
                    timeout=jitter_ms / 1000,
                )
            except asyncio.TimeoutError:
                self._tts_task.cancel()

        while not self._tts_output_queue.empty():
            try:
                self._tts_output_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._cancel_event.clear()

        await self._fsm.transition(FSMState.LISTENING, reason="resume_listening")

    async def handle_cancel(self) -> None:
        self._cancel_event.set()
        if self._barge_in_monitor_task and not self._barge_in_monitor_task.done():
            self._barge_in_monitor_task.cancel()
        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
        await self._fsm.reset()

    async def handle_timeout(self) -> None:
        if self._fsm.state == FSMState.ERROR and not self._fsm.should_auto_recover():
            await self._emit("error", {"message": "Too many consecutive errors, reconnecting required"})
            return
        if self._fsm.state != FSMState.LISTENING:
            return
        await self._emit(MessageType.LISTENING_TIMEOUT.value, {
            "timeout_seconds": self._settings.listening.timeout_seconds,
        })
        self._audio_buffer.clear()
        await self._fsm.force_state(FSMState.IDLE, reason="listening_timeout")

    async def _emit(self, msg_type: str, payload: dict[str, Any]) -> None:
        if self._event_callback is not None:
            await self._event_callback(msg_type, payload)

    async def _on_fsm_transition(
        self, source: FSMState, target: FSMState, reason: str
    ) -> None:
        logger.debug(
            "fsm transition",
            session_id=self._session_id,
            source=source.value,
            target=target.value,
            reason=reason,
        )

    async def _run_stt(self, audio_data: bytes) -> Any:
        try:
            result = await self._stt.transcribe(audio_data)
            text = result.get("text", "").strip()
            await self._emit(MessageType.TRANSCRIPT_FINAL.value, {
                "text": text,
                "confidence": result.get("confidence", 0.0),
            })
            return result
        except Exception as e:
            await self._fsm.transition(FSMState.ERROR, reason="stt_failure")
            await self._emit("error", {"message": f"STT failed: {e}"})
            raise STTError(f"STT transcription failed: {e}") from e

    async def _run_llm_and_tts(self, transcript: str) -> None:
        chunker = SentenceChunker()
        response_parts: list[str] = []

        self._prompt_manager.add_user_turn(transcript)
        messages = self._prompt_manager.build_messages()

        try:
            async for llm_token in self._llm.generate(messages, stream=True):
                if self._cancel_event.is_set():
                    return

                response_parts.append(llm_token)
                await self._emit(MessageType.LLM_TOKEN.value, {"token": llm_token})

                async for sentence in chunker.add_token(llm_token):
                    if sentence.strip():
                        await self._synthesize_sentence(sentence)

            async for sentence in chunker.flush():
                if sentence.strip():
                    await self._synthesize_sentence(sentence)

        except Exception as e:
            await self._fsm.transition(FSMState.ERROR, reason="llm_failure")
            await self._emit("error", {"message": f"LLM failed: {e}"})
            return

        response_text = "".join(response_parts)
        self._prompt_manager.add_assistant_turn(response_text)
        await self._emit(MessageType.LLM_COMPLETE.value, {"text": response_text})

        if self._fsm.state == FSMState.SPEAKING:
            await self._fsm.transition(FSMState.IDLE, reason="tts_complete")
            await self._emit(MessageType.TTS_COMPLETE.value, {
                "bytes": 0,
            })

        await self._tts_output_queue.put(None)

    async def _synthesize_sentence(self, sentence: str) -> None:
        if self._cancel_event.is_set():
            return

        try:
            audio_bytes = await self._tts.synthesize(sentence)
        except Exception:
            await self._fsm.transition(FSMState.ERROR, reason="tts_failure")
            return

        raw_pcm = _extract_pcm_from_wav(audio_bytes)
        if not raw_pcm:
            return

        if self._fsm.state == FSMState.PROCESSING:
            await self._fsm.transition(FSMState.SPEAKING, reason="tts_ready")
            await self._emit(MessageType.TTS_START.value, {"bytes": len(raw_pcm)})

        audio_cfg = self._settings.audio
        frame_size = audio_cfg.channels * audio_cfg.sample_width
        chunk_bytes = max(
            frame_size,
            audio_cfg.sample_rate * frame_size * 200 // 1000,
        )

        offset = 0
        while offset < len(raw_pcm):
            if self._cancel_event.is_set() or self._fsm.state == FSMState.INTERRUPTED:
                return

            end = offset + chunk_bytes
            chunk_data = raw_pcm[offset:end]
            is_final = end >= len(raw_pcm)

            await self._emit(MessageType.TTS_AUDIO_CHUNK.value, {
                "bytes": len(chunk_data),
                "is_final": is_final,
            })

            await self._tts_output_queue.put(
                AudioChunk(data=chunk_data, is_final=is_final)
            )

            offset = end
            await asyncio.sleep(0)

