from __future__ import annotations

from enum import Enum


class FSMState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    TOOL_WAITING = "tool_waiting"
    ERROR = "error"


TRANSITIONS: dict[tuple[FSMState, FSMState], str] = {
    (FSMState.IDLE, FSMState.LISTENING): "vad_speech_start",
    (FSMState.IDLE, FSMState.ERROR): "internal_error",
    (FSMState.LISTENING, FSMState.PROCESSING): "vad_speech_end",
    (FSMState.LISTENING, FSMState.ERROR): "stt_failure",
    (FSMState.PROCESSING, FSMState.SPEAKING): "tts_ready",
    (FSMState.PROCESSING, FSMState.TOOL_WAITING): "tool_call",
    (FSMState.PROCESSING, FSMState.INTERRUPTED): "user_interrupt",
    (FSMState.PROCESSING, FSMState.ERROR): "llm_failure",
    (FSMState.SPEAKING, FSMState.IDLE): "tts_complete",
    (FSMState.SPEAKING, FSMState.INTERRUPTED): "barge_in",
    (FSMState.SPEAKING, FSMState.ERROR): "tts_failure",
    (FSMState.INTERRUPTED, FSMState.LISTENING): "resume_listening",
    (FSMState.INTERRUPTED, FSMState.ERROR): "interrupt_timeout",
    (FSMState.TOOL_WAITING, FSMState.PROCESSING): "tool_result_ready",
    (FSMState.TOOL_WAITING, FSMState.ERROR): "tool_failure",
    (FSMState.ERROR, FSMState.IDLE): "recovery_timeout",
}

AUDIO_INPUT_STATES: frozenset[FSMState] = frozenset({
    FSMState.IDLE,
    FSMState.LISTENING,
    FSMState.INTERRUPTED,
})

INTERRUPTIBLE_STATES: frozenset[FSMState] = frozenset({
    FSMState.SPEAKING,
    FSMState.PROCESSING,
})

