#!/usr/bin/env python3
"""Turn-based voice CLI client.

Records audio on keypress, sends to orchestrator `/voice` pipeline,
plays back the spoken response, and reports per-stage timing.

Usage:
    python scripts/cli_voice.py                          # record via mic, play via speaker
    python scripts/cli_voice.py --input file.wav          # use WAV file instead of mic
    python scripts/cli_voice.py --output response.wav     # save response to file
    python scripts/cli_voice.py --orchestrator http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Turn-based voice CLI for J.A.R.V.I.S.")
    p.add_argument(
        "--orchestrator", default="http://localhost:8000", help="Orchestrator base URL"
    )
    p.add_argument(
        "--input", "-i", type=Path, help="Read WAV file instead of recording"
    )
    p.add_argument("--output", "-o", type=Path, help="Save response audio to file")
    p.add_argument(
        "--list-devices", action="store_true", help="List audio devices and exit"
    )
    return p


def record_from_mic(duration: float = 10.0, sample_rate: int = 16000) -> bytes:
    try:
        import sounddevice as sd  # type: ignore[import-untyped]
    except ImportError:
        print("sounddevice not installed. Use --input <file> instead.", file=sys.stderr)
        sys.exit(1)

    print(f"Recording {duration}s of audio...")
    recording = sd.rec(
        int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16"
    )
    sd.wait()
    print("Recording complete.")

    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(recording.tobytes())
    return buf.getvalue()


def read_wav(path: Path) -> bytes:
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_bytes()


def save_wav(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    print(f"Response saved to {path}")


def play_audio(data: bytes) -> None:
    try:
        import sounddevice as sd  # type: ignore[import-untyped]
    except ImportError:
        print(
            "sounddevice not installed. Use --output <file> to save instead.",
            file=sys.stderr,
        )
        return

    import io
    import wave

    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            sample_rate = wf.getframerate()
            sd.play(frames, samplerate=sample_rate)
            sd.wait()
    except Exception as e:
        print(f"Playback failed: {e}", file=sys.stderr)


def run_pipeline(client: httpx.Client, audio_bytes: bytes) -> tuple[float, bytes, dict]:
    stage_times: dict[str, float] = {}

    t0 = time.perf_counter()
    resp = client.post(
        "/voice", content=audio_bytes, headers={"Content-Type": "audio/wav"}
    )
    t1 = time.perf_counter()
    stage_times["total"] = t1 - t0

    if resp.status_code == 400:
        print(f"Error: {resp.json().get('detail', 'Bad request')}", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"Error: HTTP {resp.status_code}", file=sys.stderr)
        sys.exit(1)

    transcription = resp.headers.get("X-Transcription", "")
    response_text = resp.headers.get("X-Response", "")
    confidence = resp.headers.get("X-Confidence", "0")

    return (
        stage_times["total"],
        resp.content,
        {
            "transcription": transcription,
            "response_text": response_text,
            "confidence": confidence,
        },
    )


def list_devices() -> None:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice not installed.", file=sys.stderr)
        sys.exit(1)
    print(sd.query_devices())


def main() -> None:
    args = build_parser().parse_args()

    if args.list_devices:
        list_devices()
        return

    base_url = args.orchestrator.rstrip("/")

    audio_bytes = read_wav(args.input) if args.input else record_from_mic()

    total_time, response_audio, info = run_pipeline(
        httpx.Client(base_url=base_url, timeout=120.0), audio_bytes
    )

    print(f"Transcription: {info['transcription']}")
    print(f"Response: {info['response_text']}")
    print(f"Confidence: {info['confidence']}")
    print(f"Round-trip time: {total_time:.2f}s")

    if args.output:
        save_wav(args.output, response_audio)
    else:
        play_audio(response_audio)


if __name__ == "__main__":
    main()
