#!/usr/bin/env python3
"""Streaming latency benchmark for the voice pipeline.

Measures key latency metrics for the streaming voice pipeline:
  - End-of-speech → first STT partial
  - Final transcript → first LLM token
  - First sentence → first TTS audio byte
  - Total voice-to-voice latency

Uses mocked STT/LLM/TTS services for deterministic measurements.

Usage:
    python scripts/bench_streaming.py
    python scripts/bench_streaming.py --iterations 10
    python scripts/bench_streaming.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field

SAMPLE_RATE = 16000


@dataclass
class BenchmarkResult:
    """Results from a single benchmark iteration."""

    iteration: int
    stt_latency_ms: float = 0.0       # End-of-speech → transcript
    llm_first_token_ms: float = 0.0   # Transcript → first LLM token
    tts_first_byte_ms: float = 0.0    # LLM complete → first TTS byte
    total_latency_ms: float = 0.0     # End-of-speech → last TTS byte
    transcript: str = ""
    response_text: str = ""


@dataclass
class BenchmarkStats:
    """Aggregate statistics across iterations."""

    stt_latency_ms: list[float] = field(default_factory=list)
    llm_first_token_ms: list[float] = field(default_factory=list)
    tts_first_byte_ms: list[float] = field(default_factory=list)
    total_latency_ms: list[float] = field(default_factory=list)

    def add(self, r: BenchmarkResult) -> None:
        if r.stt_latency_ms > 0:
            self.stt_latency_ms.append(r.stt_latency_ms)
        if r.llm_first_token_ms > 0:
            self.llm_first_token_ms.append(r.llm_first_token_ms)
        if r.tts_first_byte_ms > 0:
            self.tts_first_byte_ms.append(r.tts_first_byte_ms)
        if r.total_latency_ms > 0:
            self.total_latency_ms.append(r.total_latency_ms)

    def _pct(self, values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        return sorted(values)[int(len(values) * pct / 100)]

    def report(self) -> str:
        lines = [
            "=" * 60,
            "  Streaming Latency Benchmark Report",
            "=" * 60,
        ]
        for name, values in [
            ("STT (EOS → transcript)", self.stt_latency_ms),
            ("LLM (transcript → first token)", self.llm_first_token_ms),
            ("TTS (LLM complete → first byte)", self.tts_first_byte_ms),
            ("Total (EOS → last byte)", self.total_latency_ms),
        ]:
            if not values:
                lines.append(f"  {name}: No data")
                continue
            lines.append(f"  {name}:")
            lines.append(f"    p50:  {self._pct(values, 50):8.1f} ms")
            lines.append(f"    p95:  {self._pct(values, 95):8.1f} ms")
            lines.append(f"    p99:  {self._pct(values, 99):8.1f} ms")
            lines.append(f"    mean: {statistics.mean(values):8.1f} ms")
            lines.append(f"    min:  {min(values):8.1f} ms")
            lines.append(f"    max:  {max(values):8.1f} ms")
        lines.append("=" * 60)
        return "\n".join(lines)


class StreamingBenchmark:
    """Measures streaming pipeline latency using mocked services."""

    def __init__(self, iterations: int = 5, verbose: bool = False) -> None:
        self.iterations = iterations
        self.verbose = verbose
        self.stats = BenchmarkStats()

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  {msg}")

    def _make_audio(self, duration_ms: int = 100) -> bytes:
        """Generate a synthetic audio chunk."""
        import math
        num_samples = SAMPLE_RATE * duration_ms // 1000
        samples = bytearray()
        for i in range(num_samples):
            val = int(math.sin(2 * math.pi * 440 * i / SAMPLE_RATE) * 8000)
            samples.extend(val.to_bytes(2, "little", signed=True))
        return bytes(samples)

    async def run_iteration(self, iteration: int) -> BenchmarkResult:
        """Run a single benchmark iteration with mocked services."""
        result = BenchmarkResult(iteration=iteration)

        # Mock STT client
        class MockSTT:
            async def transcribe(self, audio_bytes):
                await asyncio.sleep(0.05)  # Simulate STT latency
                return {"text": "what is the weather today", "language": "en",
                        "segments": [], "confidence": 0.95}

            async def check_vad(self, audio_chunk):
                return {"is_speech": False, "probability": 0.1,
                        "silence_duration_ms": 900}

            async def reset_vad(self):
                pass

        # Mock TTS client
        class MockTTS:
            async def synthesize(self, text):
                await asyncio.sleep(0.08)  # Simulate TTS latency
                return self._make_audio(500)

            def _make_audio(self, duration_ms):
                return _make_audio(duration_ms)

        # Mock LLM client
        class MockLLM:
            async def generate(self, messages, stream=True):
                tokens = ["The", " weather", " today", " is", " sunny", "."]
                for t in tokens:
                    await asyncio.sleep(0.01)  # Simulate token generation
                    yield t

        stt = MockSTT()
        tts = MockTTS()
        llm = MockLLM()

        # Track timing
        eos_time = 0.0
        transcript_time = 0.0
        first_token_time = 0.0
        llm_complete_time = 0.0
        first_tts_byte_time = 0.0
        last_tts_byte_time = 0.0

        # Simulate pipeline
        # Step 1: Send some audio
        audio_buffer = bytearray()
        for _ in range(5):
            chunk = _make_audio(200)
            audio_buffer.extend(chunk)
            await asyncio.sleep(0.01)

        # Step 2: End-of-speech (simulate VAD end)
        eos_time = time.monotonic()
        self._log(f"  [iter {iteration}] EOS detected")

        # Step 3: STT
        stt_result = await stt.transcribe(bytes(audio_buffer))
        transcript_time = time.monotonic()
        result.transcript = stt_result.get("text", "")
        result.stt_latency_ms = (transcript_time - eos_time) * 1000
        self._log(f"  [iter {iteration}] STT: {result.stt_latency_ms:.1f}ms")

        # Step 4: LLM streaming
        first_token = True
        response_parts = []
        async for token in llm.generate([{"role": "user", "content": result.transcript}]):
            if first_token:
                first_token_time = time.monotonic()
                result.llm_first_token_ms = (first_token_time - transcript_time) * 1000
                first_token = False
                self._log(f"  [iter {iteration}] First LLM token: {result.llm_first_token_ms:.1f}ms")
            response_parts.append(token)
            await asyncio.sleep(0)

        result.response_text = "".join(response_parts)
        llm_complete_time = time.monotonic()
        self._log(f"  [iter {iteration}] LLM complete: {(llm_complete_time - first_token_time) * 1000:.1f}ms")

        # Step 5: TTS
        if result.response_text.strip():
            await tts.synthesize(result.response_text)
            first_tts_byte_time = time.monotonic()
            result.tts_first_byte_ms = (first_tts_byte_time - llm_complete_time) * 1000
            self._log(f"  [iter {iteration}] First TTS byte: {result.tts_first_byte_ms:.1f}ms")

            last_tts_byte_time = time.monotonic()
            result.total_latency_ms = (last_tts_byte_time - eos_time) * 1000
            self._log(f"  [iter {iteration}] Total: {result.total_latency_ms:.1f}ms")

        return result

    async def run(self) -> BenchmarkStats:
        """Run all iterations and collect statistics."""
        print(f"\nRunning {self.iterations} benchmark iterations...")  # noqa: T201

        for i in range(self.iterations):
            result = await self.run_iteration(i + 1)
            self.stats.add(result)

            print(  # noqa: T201
                f"  Iter {i + 1}: "
                f"STT={result.stt_latency_ms:.0f}ms "
                f"LLM={result.llm_first_token_ms:.0f}ms "
                f"TTS={result.tts_first_byte_ms:.0f}ms "
                f"Total={result.total_latency_ms:.0f}ms"
            )

        return self.stats


def _make_audio(duration_ms: int) -> bytes:
    """Generate synthetic audio bytes."""
    import math
    num_samples = SAMPLE_RATE * duration_ms // 1000
    samples = bytearray()
    for i in range(num_samples):
        val = int(math.sin(2 * math.pi * 440 * i / SAMPLE_RATE) * 8000)
        samples.extend(val.to_bytes(2, "little", signed=True))
    return bytes(samples)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Streaming latency benchmark for Phase 2.5"
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=5,
        help="Number of benchmark iterations (default: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed per-iteration information",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    benchmark = StreamingBenchmark(
        iterations=args.iterations,
        verbose=args.verbose,
    )

    stats = asyncio.run(benchmark.run())

    if args.json:
        print(json.dumps({
            "stt_latency_ms": {
                "p50": statistics.median(stats.stt_latency_ms) if stats.stt_latency_ms else 0,
                "values": stats.stt_latency_ms,
            },
            "llm_first_token_ms": {
                "p50": statistics.median(stats.llm_first_token_ms) if stats.llm_first_token_ms else 0,
                "values": stats.llm_first_token_ms,
            },
            "tts_first_byte_ms": {
                "p50": statistics.median(stats.tts_first_byte_ms) if stats.tts_first_byte_ms else 0,
                "values": stats.tts_first_byte_ms,
            },
            "total_latency_ms": {
                "p50": statistics.median(stats.total_latency_ms) if stats.total_latency_ms else 0,
                "values": stats.total_latency_ms,
            },
        }, indent=2))
    else:
        print(stats.report())


if __name__ == "__main__":
    main()
