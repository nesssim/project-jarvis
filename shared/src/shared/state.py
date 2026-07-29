from __future__ import annotations

from enum import Enum


class OrchestratorState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    TOOL_WAITING = "tool_waiting"
    ERROR = "error"


class StateTransition:
    def __init__(
        self, from_state: OrchestratorState, to_state: OrchestratorState, event: str
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.event = event


TRANSITIONS: list[StateTransition] = [
    StateTransition(OrchestratorState.IDLE, OrchestratorState.LISTENING, "wake_word"),
    StateTransition(OrchestratorState.IDLE, OrchestratorState.LISTENING, "vad_trigger"),
    StateTransition(OrchestratorState.LISTENING, OrchestratorState.IDLE, "timeout"),
    StateTransition(
        OrchestratorState.LISTENING, OrchestratorState.PROCESSING, "end_of_speech"
    ),
    StateTransition(
        OrchestratorState.PROCESSING, OrchestratorState.SPEAKING, "tts_ready"
    ),
    StateTransition(
        OrchestratorState.PROCESSING, OrchestratorState.TOOL_WAITING, "tool_call"
    ),
    StateTransition(
        OrchestratorState.TOOL_WAITING, OrchestratorState.PROCESSING, "tool_result"
    ),
    StateTransition(
        OrchestratorState.SPEAKING, OrchestratorState.INTERRUPTED, "barge_in"
    ),
    StateTransition(
        OrchestratorState.INTERRUPTED, OrchestratorState.LISTENING, "resume_listening"
    ),
    StateTransition(OrchestratorState.ERROR, OrchestratorState.IDLE, "recovery"),
]

ALLOWED_TRANSITIONS: dict[OrchestratorState, set[str]] = {}
for t in TRANSITIONS:
    if t.from_state not in ALLOWED_TRANSITIONS:
        ALLOWED_TRANSITIONS[t.from_state] = set()
    ALLOWED_TRANSITIONS[t.from_state].add(t.event)
ALLOWED_TRANSITIONS[OrchestratorState.ERROR] = {"recovery"}
for s in OrchestratorState:
    if s not in ALLOWED_TRANSITIONS:
        ALLOWED_TRANSITIONS[s] = set()
    ALLOWED_TRANSITIONS[s].add("error")


def is_valid_transition(from_state: OrchestratorState, event: str) -> bool:
    return event in ALLOWED_TRANSITIONS.get(from_state, set())


def next_state(from_state: OrchestratorState, event: str) -> OrchestratorState:
    if event == "error":
        return OrchestratorState.ERROR
    for t in TRANSITIONS:
        if t.from_state == from_state and t.event == event:
            return t.to_state
    raise ValueError(f"Invalid transition: {from_state.value} -> {event}")
