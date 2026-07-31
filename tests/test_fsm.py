from __future__ import annotations

import asyncio

import pytest
from orchestrator.core.state_machine import StateMachine, TransitionError
from shared.state import (
    AUDIO_INPUT_STATES,
    INTERRUPTIBLE_STATES,
    TRANSITIONS,
    FSMState,
)


class TestFSMStateEnum:
    def test_enum_values(self):
        assert FSMState.IDLE.value == "idle"
        assert FSMState.LISTENING.value == "listening"
        assert FSMState.PROCESSING.value == "processing"
        assert FSMState.SPEAKING.value == "speaking"
        assert FSMState.INTERRUPTED.value == "interrupted"
        assert FSMState.TOOL_WAITING.value == "tool_waiting"
        assert FSMState.ERROR.value == "error"

    def test_all_states_present(self):
        expected = {
            FSMState.IDLE,
            FSMState.LISTENING,
            FSMState.PROCESSING,
            FSMState.SPEAKING,
            FSMState.INTERRUPTED,
            FSMState.TOOL_WAITING,
            FSMState.ERROR,
        }
        assert set(FSMState) == expected

    def test_transitions_count(self):
        assert len(TRANSITIONS) >= 15

    def test_audio_input_states(self):
        assert FSMState.IDLE in AUDIO_INPUT_STATES
        assert FSMState.LISTENING in AUDIO_INPUT_STATES
        assert FSMState.INTERRUPTED in AUDIO_INPUT_STATES
        assert FSMState.PROCESSING not in AUDIO_INPUT_STATES
        assert FSMState.SPEAKING not in AUDIO_INPUT_STATES

    def test_interruptible_states(self):
        assert FSMState.SPEAKING in INTERRUPTIBLE_STATES
        assert FSMState.PROCESSING in INTERRUPTIBLE_STATES
        assert FSMState.IDLE not in INTERRUPTIBLE_STATES
        assert FSMState.LISTENING not in INTERRUPTIBLE_STATES


class TestStateMachineTransitions:
    @pytest.mark.asyncio
    async def test_valid_transition_idle_to_listening(self):
        fsm = StateMachine()
        result = await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert result is True
        assert fsm.state == FSMState.LISTENING

    @pytest.mark.asyncio
    async def test_valid_transition_listening_to_processing(self):
        fsm = StateMachine()
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        assert fsm.state == FSMState.PROCESSING

    @pytest.mark.asyncio
    async def test_valid_transition_processing_to_speaking(self):
        fsm = StateMachine()
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        await fsm.transition(FSMState.SPEAKING, reason="tts_ready")
        assert fsm.state == FSMState.SPEAKING

    @pytest.mark.asyncio
    async def test_valid_transition_speaking_to_idle(self):
        fsm = StateMachine()
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        await fsm.transition(FSMState.SPEAKING, reason="tts_ready")
        await fsm.transition(FSMState.IDLE, reason="tts_complete")
        assert fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        fsm = StateMachine()
        with pytest.raises(TransitionError) as exc:
            await fsm.transition(FSMState.SPEAKING, reason="invalid")
        assert exc.value.source == FSMState.IDLE
        assert exc.value.target == FSMState.SPEAKING
        assert FSMState.LISTENING in exc.value.valid_targets
        assert FSMState.ERROR in exc.value.valid_targets

    @pytest.mark.asyncio
    async def test_error_transitions(self):
        fsm = StateMachine()
        await fsm.transition(FSMState.ERROR, reason="internal_error")
        assert fsm.state == FSMState.ERROR
        await fsm.transition(FSMState.IDLE, reason="recovery_timeout")
        assert fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_barge_in_transition(self):
        fsm = StateMachine()
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        await fsm.transition(FSMState.SPEAKING, reason="tts_ready")
        await fsm.transition(FSMState.INTERRUPTED, reason="barge_in")
        assert fsm.state == FSMState.INTERRUPTED

    @pytest.mark.asyncio
    async def test_full_cycle(self):
        fsm = StateMachine()
        assert fsm.state == FSMState.IDLE
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert fsm.state == FSMState.LISTENING
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        assert fsm.state == FSMState.PROCESSING
        await fsm.transition(FSMState.SPEAKING, reason="tts_ready")
        assert fsm.state == FSMState.SPEAKING
        await fsm.transition(FSMState.IDLE, reason="tts_complete")
        assert fsm.state == FSMState.IDLE


class TestStateMachineBargeIn:
    @pytest.mark.asyncio
    async def test_barge_in_only_from_interruptible(self):
        fsm = StateMachine(FSMState.IDLE)
        assert await fsm.request_barge_in() is False

        await fsm.force_state(FSMState.SPEAKING, reason="test")
        assert await fsm.request_barge_in() is True
        assert fsm.state == FSMState.INTERRUPTED

    @pytest.mark.asyncio
    async def test_barge_in_from_processing(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.PROCESSING, reason="test")
        assert await fsm.request_barge_in() is True
        assert fsm.state == FSMState.INTERRUPTED

    @pytest.mark.asyncio
    async def test_barge_in_not_from_listening(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.LISTENING, reason="test")
        assert await fsm.request_barge_in() is False


class TestStateMachineConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_transitions_serialized(self):
        fsm = StateMachine()

        async def t1():
            return await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")

        async def t2():
            return await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")

        results = await asyncio.gather(t1(), t2(), return_exceptions=True)
        assert all(r is True or isinstance(r, TransitionError) for r in results)


class TestStateMachineErrorRecovery:
    @pytest.mark.asyncio
    async def test_error_counting(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 1
        await fsm.force_state(FSMState.IDLE, reason="recover")
        assert fsm.consecutive_errors == 0
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 1

    @pytest.mark.asyncio
    async def test_triple_failure_guard(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 1
        assert fsm.should_auto_recover() is True
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 2
        assert fsm.should_auto_recover() is True
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 3
        assert fsm.should_auto_recover() is False

    @pytest.mark.asyncio
    async def test_reset_clears_errors(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.consecutive_errors == 1
        await fsm.reset()
        assert fsm.consecutive_errors == 0
        assert fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_should_auto_recover_after_reset(self):
        fsm = StateMachine()
        await fsm.force_state(FSMState.ERROR, reason="test")
        await fsm.force_state(FSMState.ERROR, reason="test")
        await fsm.force_state(FSMState.ERROR, reason="test")
        assert fsm.should_auto_recover() is False
        await fsm.reset()
        assert fsm.should_auto_recover() is True


class TestStateMachineStateDuration:
    @pytest.mark.asyncio
    async def test_state_duration_ms(self):
        fsm = StateMachine()
        d1 = fsm.state_duration_ms
        assert d1 < 100
        await asyncio.sleep(0.05)
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        d2 = fsm.state_duration_ms
        assert d2 >= 0

    @pytest.mark.asyncio
    async def test_state_duration_updates_on_transition(self):
        fsm = StateMachine()
        await asyncio.sleep(0.01)
        d1 = fsm.state_duration_ms
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        d2 = fsm.state_duration_ms
        assert d2 < d1


class TestStateMachineCallbacks:
    @pytest.mark.asyncio
    async def test_on_transition_callback(self):
        calls = []

        async def cb(src, tgt, reason):
            calls.append((src, tgt, reason))

        fsm = StateMachine(on_transition=cb)
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert len(calls) == 1
        assert calls[0][0] == FSMState.IDLE
        assert calls[0][1] == FSMState.LISTENING

    @pytest.mark.asyncio
    async def test_on_enter_callback(self):
        calls = []

        fsm = StateMachine()

        @fsm.on_enter(FSMState.LISTENING)
        async def enter_listening():
            calls.append("entered_listening")

        @fsm.on_enter(FSMState.PROCESSING)
        async def enter_processing():
            calls.append("entered_processing")

        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert "entered_listening" in calls
        assert "entered_processing" not in calls

        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        assert "entered_processing" in calls

    @pytest.mark.asyncio
    async def test_on_exit_callback(self):
        exit_calls = []
        enter_calls = []

        fsm = StateMachine()

        @fsm.on_exit(FSMState.IDLE)
        async def exit_idle():
            exit_calls.append("exited_idle")

        @fsm.on_enter(FSMState.LISTENING)
        async def enter_listening():
            enter_calls.append("entered_listening")

        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert "exited_idle" in exit_calls
        assert "entered_listening" in enter_calls

    @pytest.mark.asyncio
    async def test_force_state_triggers_callbacks(self):
        calls = []

        fsm = StateMachine()

        @fsm.on_enter(FSMState.ERROR)
        async def enter_error():
            calls.append("entered_error")

        await fsm.force_state(FSMState.ERROR, reason="test")
        assert "entered_error" in calls

    @pytest.mark.asyncio
    async def test_interruptible_states_property(self):
        fsm = StateMachine()
        assert not fsm.is_interruptible
        await fsm.force_state(FSMState.SPEAKING, reason="test")
        assert fsm.is_interruptible
        await fsm.force_state(FSMState.PROCESSING, reason="test")
        assert fsm.is_interruptible

    @pytest.mark.asyncio
    async def test_can_accept_audio(self):
        fsm = StateMachine()
        assert fsm.can_accept_audio
        await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert fsm.can_accept_audio
        await fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        assert not fsm.can_accept_audio
