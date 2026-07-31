#!/usr/bin/env python3
"""Barge-in jitter tuning experiment.

Measures the trade-off between interrupt latency and audio quality
for different jitter durations. Outputs a report suitable for
choosing the optimal barge_in_jitter_ms value.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from collections.abc import AsyncIterator

from shared.config import LLMConfig, Settings

from orchestrator.clients.llm import BaseLLMClient
from orchestrator.core.pipeline import RealtimePipeline
from orchestrator.core.prompt import PromptManager
from orchestrator.core.state_machine import FSMState
from shared.state import FSMState as FSMStateEnum


@dataclass
class TuningResult:
    jitter_ms: int
    avg_interrupt_latency_ms: float = 0.0
    max_interrupt_latency_ms: float = 0.0
    audio_clip_count: int = 0
    quality_score: float = 0.0
    recommendation: str = ""


class _MockSTT:
    async def transcribe(self, audio_bytes: bytes) -> dict:
        await asyncio.sleep(0.01)
        return {"text": "test transcript", "confidence": 0.95}

    async def close(self) -> None:
        pass


class _MockTTS:
    def __init__(self, duration_ms: float = 500) -> None:
        self._duration = duration_ms / 1000.0

    async def synthesize(self, text: str) -> bytes:
        await asyncio.sleep(self._duration)
        return b"RIFF" + b"\x00" * 16000

    async def close(self) -> None:
        pass


class _MockLLM(BaseLLMClient):
    def __init__(self, config: LLMConfig | None = None) -> None:
        super().__init__(config or LLMConfig())

    async def generate(
        self,
        messages: list[dict[str, str]],
        stream: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        words = ["this ", "is ", "a ", "long ", "response ", "that ",
                 "will ", "be ", "interrupted ", "by ", "barge-in "]
        for w in words:
            await asyncio.sleep(0.05)
            yield w

    async def close(self) -> None:
        pass


async def run_experiment(
    jitter_ms: int,
    num_trials: int = 10,
) -> TuningResult:
    stt = _MockSTT()
    tts = _MockTTS(duration_ms=300)
    llm = _MockLLM()
    settings = Settings(
        redis={"url": "redis://:test@localhost:6379/0"},
        logging={"level": "WARNING", "format": "text"},
        listening={
            "barge_in_enabled": True,
            "barge_in_jitter_ms": jitter_ms,
        },
        audio={
            "sample_rate": 16000,
            "channels": 1,
            "sample_width": 2,
            "chunk_size_ms": 100,
        },
    )
    prompt = PromptManager(settings.llm)

    latencies: list[float] = []
    clip_count = 0

    for trial in range(num_trials):
        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt,
            settings=settings,
        )

        await pipeline.fsm.force_state(FSMState.SPEAKING, reason="test")

        barge_in_delay = random.uniform(0.05, 0.3)
        await asyncio.sleep(barge_in_delay)

        start = time.monotonic()
        await pipeline.handle_barge_in()
        elapsed_ms = (time.monotonic() - start) * 1000
        latencies.append(elapsed_ms)

        if elapsed_ms > jitter_ms * 1.5:
            clip_count += 1

        await pipeline.handle_cancel()

    if not latencies:
        return TuningResult(jitter_ms=jitter_ms)

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    quality_score = max(0.0, 1.0 - (clip_count / num_trials) * 0.5)
    quality_score = max(0.0, quality_score - (jitter_ms / 2000.0))

    result = TuningResult(
        jitter_ms=jitter_ms,
        avg_interrupt_latency_ms=round(avg_latency, 1),
        max_interrupt_latency_ms=round(max_latency, 1),
        audio_clip_count=clip_count,
        quality_score=round(quality_score, 2),
    )

    return result


async def main() -> None:
    jitter_values = [25, 50, 100, 150, 200, 300, 500]
    results: list[TuningResult] = []

    print("Running barge-in jitter tuning experiment...\n")
    for jitter in jitter_values:
        result = await run_experiment(jitter, num_trials=10)
        results.append(result)
        print(f"  jitter={jitter:>4}ms  "
              f"avg_latency={result.avg_interrupt_latency_ms:>6.1f}ms  "
              f"max_latency={result.max_interrupt_latency_ms:>6.1f}ms  "
              f"clips={result.audio_clip_count:>2}  "
              f"quality={result.quality_score:.2f}")

    print()
    print(f"{'Jitter (ms)':>10} {'Avg Latency':>12} {'Max Latency':>12} {'Clips':>7} {'Quality':>9}")
    print("-" * 50)
    for r in results:
        print(f"{r.jitter_ms:>10} {r.avg_interrupt_latency_ms:>12.1f} {r.max_interrupt_latency_ms:>12.1f} {r.audio_clip_count:>7} {r.quality_score:>9.2f}")

    if results:
        def score(r: TuningResult) -> float:
            return r.avg_interrupt_latency_ms * 2 + (1 - r.quality_score) * 1000

        best = min(results, key=score)
        print(f"\nRecommended jitter: {best.jitter_ms}ms")
        print(f"  (score={score(best):.1f}, "
              f"latency={best.avg_interrupt_latency_ms}ms, "
              f"quality={best.quality_score})")


if __name__ == "__main__":
    asyncio.run(main())
