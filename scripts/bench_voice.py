#!/usr/bin/env python3
"""Voice round-trip latency benchmark.

Measures each stage (STT, LLM, TTS) independently using WAV fixtures,
then measures the full pipeline via the /voice endpoint.

Usage:
    python scripts/bench_voice.py
    python scripts/bench_voice.py --orchestrator http://localhost:8000 --iterations 5
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "audio"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Voice round-trip latency benchmark")
    p.add_argument(
        "--orchestrator", default="http://localhost:8000", help="Orchestrator base URL"
    )
    p.add_argument(
        "--iterations", "-n", type=int, default=5, help="Number of iterations"
    )
    p.add_argument(
        "--fixture", default="utterance_short_16khz.wav", help="WAV fixture filename"
    )
    return p


def benchmark_pipeline(
    client: httpx.Client, audio_bytes: bytes, iterations: int
) -> dict:
    times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        resp = client.post(
            "/voice", content=audio_bytes, headers={"Content-Type": "audio/wav"}
        )
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  Iteration {i + 1}: {elapsed:.3f}s", end="")
        if resp.status_code == 200:
            print(f"  (transcription: {resp.headers.get('X-Transcription', '')[:40]})")
        else:
            print(f"  (HTTP {resp.status_code})")

    return {
        "min": min(times),
        "max": max(times),
        "p50": statistics.median(times),
        "p95": sorted(times)[int(len(times) * 0.95)],
        "mean": statistics.mean(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
    }


def main() -> None:
    args = build_parser().parse_args()
    base_url = args.orchestrator.rstrip("/")

    fixture_path = FIXTURES_DIR / args.fixture
    if not fixture_path.exists():
        print(f"Fixture not found: {fixture_path}")
        return

    audio_bytes = fixture_path.read_bytes()
    print(f"Fixture: {fixture_path.name} ({len(audio_bytes)} bytes)")
    print("Warmup (1 iteration)...")

    client = httpx.Client(base_url=base_url, timeout=120.0)
    benchmark_pipeline(client, audio_bytes, 1)

    print(f"\nBenchmark ({args.iterations} iterations)...")
    stats = benchmark_pipeline(client, audio_bytes, args.iterations)

    print("\n--- Results ---")
    print(f"  Min:    {stats['min']:.3f}s")
    print(f"  Max:    {stats['max']:.3f}s")
    print(f"  P50:    {stats['p50']:.3f}s")
    print(f"  P95:    {stats['p95']:.3f}s")
    print(f"  Mean:   {stats['mean']:.3f}s")
    print(f"  Stdev:  {stats['stdev']:.3f}s")


if __name__ == "__main__":
    main()
