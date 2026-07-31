from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from shared.state import FSMState

from tests.conftest import make_audio_chunk as _make_audio_chunk


def _make_mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.audio.sample_rate = 16000
    settings.audio.channels = 1
    settings.audio.sample_width = 2
    settings.audio.chunk_size_ms = 100
    settings.listening.timeout_seconds = 5
    settings.listening.silence_threshold_ms = 800
    settings.listening.barge_in_enabled = True
    settings.listening.barge_in_jitter_ms = 200
    return settings


def _llm_gen(tokens):
    async def gen(*args, **kwargs):
        for t in tokens:
            yield t

    return gen


@pytest.fixture
def mock_clients():
    stt = AsyncMock()
    stt.transcribe = AsyncMock(return_value={"text": "test", "confidence": 0.9})
    stt.check_vad = AsyncMock(
        return_value={"is_speech": True, "probability": 0.8, "silence_duration_ms": 0}
    )
    stt.reset_vad = AsyncMock()

    tts = AsyncMock()
    tts.synthesize = AsyncMock(return_value=_make_audio_chunk(200))

    llm = AsyncMock()
    llm.generate = MagicMock()

    prompt = MagicMock()
    prompt.get_system_prompt.return_value = "You are a helpful assistant."

    return stt, tts, llm, prompt


class TestRealtimePipelineStates:
    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        assert pipeline.fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_push_audio_when_idle(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        result = await pipeline.push_audio(b"\x00\x01" * 100)
        assert result is True

    @pytest.mark.asyncio
    async def test_push_audio_when_processing(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await pipeline.fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
        result = await pipeline.push_audio(b"\x00\x01" * 100)
        assert result is False

    @pytest.mark.asyncio
    async def test_push_audio_when_error(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.fsm.force_state(FSMState.ERROR, reason="test")
        result = await pipeline.push_audio(b"\x00\x01" * 100)
        assert result is False


class TestRealtimePipelinePushAudio:
    @pytest.mark.asyncio
    async def test_audio_buffered_correctly(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        data = b"\x00\x01" * 500
        await pipeline.push_audio(data)
        assert len(pipeline._audio_buffer) == len(data)


class TestRealtimePipelineCancel:
    @pytest.mark.asyncio
    async def test_cancel_resets_fsm(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        assert pipeline.fsm.state == FSMState.LISTENING
        await pipeline.handle_cancel()
        assert pipeline.fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_cancel_sets_event(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        assert not pipeline._cancel_event.is_set()
        await pipeline.handle_cancel()
        assert pipeline._cancel_event.is_set()


class TestRealtimePipelineError:
    @pytest.mark.asyncio
    async def test_stt_failure_transitions_to_error(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        stt.transcribe = AsyncMock(side_effect=Exception("STT failed"))

        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.push_audio(b"\x00\x01" * 500)
        await pipeline.fsm.transition(FSMState.LISTENING, reason="vad_speech_start")

        await pipeline.handle_speech_end()
        assert pipeline.fsm.state == FSMState.ERROR


class TestRealtimePipelineTimeout:
    @pytest.mark.asyncio
    async def test_timeout_only_from_listening(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.handle_timeout()
        assert pipeline.fsm.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_timeout_clears_buffer(self, mock_clients):
        stt, tts, llm, prompt = mock_clients
        from orchestrator.core.pipeline import RealtimePipeline

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=_make_mock_settings(),
        )
        await pipeline.push_audio(b"\x00\x01" * 500)
        await pipeline.fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
        await pipeline.handle_timeout()
        assert len(pipeline._audio_buffer) == 0
