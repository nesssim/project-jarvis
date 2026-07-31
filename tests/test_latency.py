from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from shared.config import LLMConfig, Settings

from orchestrator.clients.llm import BaseLLMClient
from orchestrator.core.pipeline import RealtimePipeline
from orchestrator.core.prompt import PromptManager
from orchestrator.core.state_machine import FSMState
from shared.state import AUDIO_INPUT_STATES
from tests.conftest import make_audio_chunk


def _stub_settings(**overrides: object) -> Settings:
    base = {
        "redis": {"url": "redis://:test@localhost:6379/0"},
        "logging": {"level": "DEBUG", "format": "text"},
        "listening": {"barge_in_jitter_ms": 50},
        "audio": {"sample_rate": 16000, "channels": 1, "sample_width": 2, "chunk_size_ms": 100},
    }
    base.update(overrides)
    return Settings(**base)


def _dummy_wav(duration_ms: int = 200) -> bytes:
    import math
    sample_rate = 16000
    num_samples = sample_rate * duration_ms // 1000
    header = bytearray()
    data_size = num_samples * 2
    # RIFF header
    header.extend(b"RIFF")
    header.extend((36 + data_size).to_bytes(4, "little"))
    header.extend(b"WAVE")
    header.extend(b"fmt ")
    header.extend((16).to_bytes(4, "little"))
    header.extend((1).to_bytes(2, "little"))
    header.extend((1).to_bytes(2, "little"))
    header.extend(sample_rate.to_bytes(4, "little"))
    header.extend((sample_rate * 2).to_bytes(4, "little"))
    header.extend((2).to_bytes(2, "little"))
    header.extend((16).to_bytes(2, "little"))
    header.extend(b"data")
    header.extend(data_size.to_bytes(4, "little"))
    samples = bytearray()
    for i in range(num_samples):
        val = int(math.sin(2 * math.pi * 440 * i / sample_rate) * 8000)
        samples.extend(val.to_bytes(2, "little", signed=True))
    return bytes(header + samples)


class _MockSTT:
    def __init__(self, delay_ms: float = 50) -> None:
        self._delay = delay_ms / 1000.0

    async def transcribe(self, audio_bytes: bytes) -> dict:
        await asyncio.sleep(self._delay)
        return {"text": "test transcript", "confidence": 0.95}

    async def close(self) -> None:
        pass


class _MockTTS:
    def __init__(self, delay_ms: float = 100) -> None:
        self._delay = delay_ms / 1000.0

    async def synthesize(self, text: str) -> bytes:
        await asyncio.sleep(self._delay)
        return _dummy_wav(300)

    async def close(self) -> None:
        pass


class _MockLLM(BaseLLMClient):
    def __init__(
        self,
        config: LLMConfig | None = None,
        ttft_ms: float = 150,
        tbt_ms: float = 30,
    ) -> None:
        super().__init__(config or LLMConfig())
        self._ttft = ttft_ms / 1000.0
        self._tbt = tbt_ms / 1000.0

    async def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        await asyncio.sleep(self._ttft)
        tokens = ["hello", " world", " this", " is", " a", " test"]
        for token in tokens:
            yield token
            await asyncio.sleep(self._tbt)

    async def close(self) -> None:
        pass


@pytest.mark.performance
@pytest.mark.asyncio
async def test_stt_ttft_under_budget() -> None:
    stt = _MockSTT(delay_ms=50)
    audio = _dummy_wav(200)
    start = time.monotonic()
    result = await stt.transcribe(audio)
    elapsed = time.monotonic() - start
    assert result["text"] == "test transcript"
    assert elapsed < 0.300


@pytest.mark.performance
@pytest.mark.asyncio
async def test_llm_ttft_under_budget() -> None:
    llm = _MockLLM(ttft_ms=100)
    start = time.monotonic()
    tokens: list[str] = []
    async for token in llm.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)
        break
    elapsed = time.monotonic() - start
    assert tokens[0] == "hello"
    assert elapsed < 0.600


@pytest.mark.performance
@pytest.mark.asyncio
async def test_llm_tbt_under_budget() -> None:
    llm = _MockLLM(ttft_ms=10, tbt_ms=20)
    gaps: list[float] = []
    prev = time.monotonic()
    async for token in llm.generate([{"role": "user", "content": "hi"}]):
        now = time.monotonic()
        if gaps or not token.startswith("hello"):
            gaps.append(now - prev)
        prev = now
    avg_gap = sum(gaps) / len(gaps) if gaps else 0.0
    assert avg_gap < 0.100


@pytest.mark.performance
@pytest.mark.asyncio
async def test_tts_ttft_under_budget() -> None:
    tts = _MockTTS(delay_ms=100)
    start = time.monotonic()
    audio = await tts.synthesize("Hello world")
    elapsed = time.monotonic() - start
    assert len(audio) > 0
    assert elapsed < 0.400


@pytest.mark.performance
@pytest.mark.asyncio
async def test_e2e_voice_to_voice_under_budget() -> None:
    stt = _MockSTT(delay_ms=30)
    tts = _MockTTS(delay_ms=50)
    llm = _MockLLM(ttft_ms=80, tbt_ms=15)
    settings = _stub_settings()
    prompt = PromptManager(
        prompts_dir="config/prompts",
        max_context_tokens=settings.llm.max_context_tokens,
    )

    events: list[tuple[str, float]] = []

    async def on_event(msg_type: str, payload: dict) -> None:
        events.append((msg_type, time.monotonic()))

    pipeline = RealtimePipeline(
        stt_client=stt,
        tts_client=tts,
        llm_client=llm,
        prompt_manager=prompt,
        settings=settings,
        event_callback=on_event,
    )

    await pipeline.fsm.transition(FSMState.LISTENING, reason="test")
    chunk = make_audio_chunk(100)
    await pipeline.push_audio(chunk)
    await pipeline.push_audio(chunk)

    start = time.monotonic()
    await pipeline.handle_speech_end()

    timeout = 5.0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for msg_type, _ in events:
            if msg_type == "tts.audio_chunk":
                elapsed = time.monotonic() - start
                assert elapsed < 3.0
                return
        await asyncio.sleep(0.01)

    pytest.fail("No TTS audio chunk received within timeout")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_barge_in_response_time() -> None:
    stt = _MockSTT(delay_ms=10)
    tts = _MockTTS(delay_ms=2000)
    llm = _MockLLM(ttft_ms=50, tbt_ms=10)
    settings = _stub_settings()
    prompt = PromptManager(
        prompts_dir="config/prompts",
        max_context_tokens=settings.llm.max_context_tokens,
    )

    pipeline = RealtimePipeline(
        stt_client=stt,
        tts_client=tts,
        llm_client=llm,
        prompt_manager=prompt,
        settings=settings,
    )

    await pipeline.fsm.force_state(FSMState.SPEAKING, reason="test")

    start = time.monotonic()
    await pipeline.handle_barge_in()
    elapsed = time.monotonic() - start

    assert pipeline.fsm.state == FSMState.LISTENING
    assert elapsed < 0.500
