from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MessageType(str, Enum):
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    VAD_SPEECH_START = "vad.speech_start"
    VAD_SPEECH_END = "vad.speech_end"
    TTS_SYNTHESIZE = "tts.synthesize"
    TTS_STOP = "tts.stop"
    TTS_AUDIO_CHUNK = "tts.audio_chunk"
    TTS_COMPLETE = "tts.complete"
    LLM_GENERATE = "llm.generate"
    LLM_CANCEL = "llm.cancel"
    LLM_TOKEN = "llm.token"
    LLM_COMPLETE = "llm.complete"
    LLM_TOOL_CALL = "llm.tool_call"
    TTS_START = "tts.start"
    INTERRUPTED = "interrupted"
    LISTENING_TIMEOUT = "listening.timeout"
    MEMORY_STORE = "memory.store"
    MEMORY_RETRIEVE = "memory.retrieve"
    MEMORY_RETRIEVE_RESULT = "memory.retrieve_result"


class Message(BaseModel):
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = Field(default_factory=time.time)
    session_id: str = ""
    user_id: str = ""

    @field_validator("request_id")
    @classmethod
    def request_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("request_id must not be empty")
        return v

    @field_validator("timestamp")
    @classmethod
    def timestamp_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("timestamp must be positive")
        return v


def create_message(
    msg_type: MessageType,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    session_id: str = "",
    user_id: str = "",
) -> Message:
    return Message(
        type=msg_type,
        payload=payload or {},
        request_id=request_id or uuid.uuid4().hex,
        timestamp=time.time(),
        session_id=session_id,
        user_id=user_id,
    )
