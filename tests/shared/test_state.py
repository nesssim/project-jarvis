from __future__ import annotations

import pytest
from shared.state import (
    ALLOWED_TRANSITIONS,
    OrchestratorState,
    is_valid_transition,
    next_state,
)


def test_all_states_have_entries() -> None:
    for state in OrchestratorState:
        assert state in ALLOWED_TRANSITIONS


def test_all_states_can_error() -> None:
    for state in OrchestratorState:
        assert is_valid_transition(state, "error")


def test_idle_transitions() -> None:
    assert is_valid_transition(OrchestratorState.IDLE, "wake_word")
    assert is_valid_transition(OrchestratorState.IDLE, "vad_trigger")
    assert not is_valid_transition(OrchestratorState.IDLE, "barge_in")
    assert not is_valid_transition(OrchestratorState.IDLE, "tool_call")


def test_listening_transitions() -> None:
    assert is_valid_transition(OrchestratorState.LISTENING, "timeout")
    assert is_valid_transition(OrchestratorState.LISTENING, "end_of_speech")
    assert not is_valid_transition(OrchestratorState.LISTENING, "tts_ready")


def test_processing_transitions() -> None:
    assert is_valid_transition(OrchestratorState.PROCESSING, "tts_ready")
    assert is_valid_transition(OrchestratorState.PROCESSING, "tool_call")
    assert not is_valid_transition(OrchestratorState.PROCESSING, "barge_in")


def test_speaking_transitions() -> None:
    assert is_valid_transition(OrchestratorState.SPEAKING, "barge_in")
    assert not is_valid_transition(OrchestratorState.SPEAKING, "end_of_speech")


def test_interrupted_transitions() -> None:
    assert is_valid_transition(OrchestratorState.INTERRUPTED, "resume_listening")
    assert not is_valid_transition(OrchestratorState.INTERRUPTED, "barge_in")


def test_tool_waiting_transitions() -> None:
    assert is_valid_transition(OrchestratorState.TOOL_WAITING, "tool_result")
    assert not is_valid_transition(OrchestratorState.TOOL_WAITING, "tts_ready")


def test_error_transition() -> None:
    assert is_valid_transition(OrchestratorState.ERROR, "recovery")


def test_next_state_happy_path() -> None:
    assert (
        next_state(OrchestratorState.IDLE, "wake_word") == OrchestratorState.LISTENING
    )
    assert (
        next_state(OrchestratorState.LISTENING, "end_of_speech")
        == OrchestratorState.PROCESSING
    )
    assert (
        next_state(OrchestratorState.PROCESSING, "tts_ready")
        == OrchestratorState.SPEAKING
    )
    assert (
        next_state(OrchestratorState.SPEAKING, "barge_in")
        == OrchestratorState.INTERRUPTED
    )
    assert (
        next_state(OrchestratorState.INTERRUPTED, "resume_listening")
        == OrchestratorState.LISTENING
    )
    assert (
        next_state(OrchestratorState.PROCESSING, "tool_call")
        == OrchestratorState.TOOL_WAITING
    )
    assert (
        next_state(OrchestratorState.TOOL_WAITING, "tool_result")
        == OrchestratorState.PROCESSING
    )
    assert next_state(OrchestratorState.LISTENING, "timeout") == OrchestratorState.IDLE
    assert next_state(OrchestratorState.ERROR, "recovery") == OrchestratorState.IDLE


def test_next_state_error_any() -> None:
    assert next_state(OrchestratorState.IDLE, "error") == OrchestratorState.ERROR
    assert next_state(OrchestratorState.SPEAKING, "error") == OrchestratorState.ERROR
    assert next_state(OrchestratorState.PROCESSING, "error") == OrchestratorState.ERROR


def test_next_state_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid transition"):
        next_state(OrchestratorState.IDLE, "barge_in")


def test_orchestrator_state_values() -> None:
    assert OrchestratorState.IDLE.value == "idle"
    assert OrchestratorState.LISTENING.value == "listening"
    assert OrchestratorState.PROCESSING.value == "processing"
    assert OrchestratorState.SPEAKING.value == "speaking"
    assert OrchestratorState.INTERRUPTED.value == "interrupted"
    assert OrchestratorState.TOOL_WAITING.value == "tool_waiting"
    assert OrchestratorState.ERROR.value == "error"
