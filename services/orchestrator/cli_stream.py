#!/usr/bin/env python3
"""Streaming voice client for J.A.R.V.I.S. (Phase 3 FSM-compatible)

Connects to the orchestrator's WebSocket streaming audio endpoint,
captures microphone audio, streams it to the server, and displays
transcription/text responses while playing back audio responses.

Usage:
    python cli_stream.py
    python cli_stream.py --url ws://localhost:8000/ws/audio
    python cli_stream.py --api-key my-secret-key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_SIZE_MS = 100  # 100ms chunks
CHUNK_BYTES = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * CHUNK_SIZE_MS // 1000


@dataclass
class StreamStats:
    """Tracking statistics for the streaming session."""

    total_audio_sent: int = 0
    partials_received: int = 0
    tokens_received: int = 0
    audio_chunks_received: int = 0
    start_time: float = 0.0
    last_partial_text: str = ""
    responses: list[str] = field(default_factory=list)


class StreamingClient:
    """Streaming WebSocket client for voice I/O."""

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        device: int | None = None,
        vad_enabled: bool = True,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.device = device
        self.vad_enabled = vad_enabled
        self.stats = StreamStats()
        self._running = False
        self._session_id = ""

    async def run(self) -> None:
        """Main run loop: connect and process audio."""
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            print(  # noqa: T201
                "Error: 'websockets' package required.\n"
                "Install: pip install websockets"
            )
            sys.exit(1)

        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        self.stats.start_time = time.time()

        try:
            async with websockets.connect(
                self.url,
                additional_headers=headers,
                max_size=2**25,  # 32MB max message
            ) as ws:
                self._running = True

                # Wait for connection message
                connected_msg = await ws.recv()
                if isinstance(connected_msg, str):
                    data = json.loads(connected_msg)
                    if data.get("type") == "connected":
                        self._session_id = data["session_id"]
                        self._print_status(
                            f"Connected! Session: {self._session_id}"
                        )
                        self._print_help()
                    elif data.get("type") == "error":
                        self._print_error(data.get("message", "Unknown error"))
                        return

                # Start audio capture and message processing concurrently
                capture_task = asyncio.create_task(
                    self._capture_audio(ws)
                )
                receive_task = asyncio.create_task(
                    self._receive_messages(ws)
                )

                # Wait for either task to complete
                done, pending = await asyncio.wait(
                    [capture_task, receive_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel remaining tasks
                for task in pending:
                    task.cancel()

                # Check for errors
                for task in done:
                    exc = task.exception()
                    if exc:
                        self._print_error(str(exc))

        except websockets.exceptions.ConnectionClosed:
            self._print_status("Connection closed")
        except OSError as e:
            self._print_error(f"Connection error: {e}")
        except Exception as e:
            self._print_error(f"Unexpected error: {e}")
        finally:
            self._running = False
            self._print_stats()

    async def _capture_audio(self, ws: Any) -> None:
        """Capture microphone audio and stream to server."""
        try:
            import sounddevice as sd  # type: ignore[import-untyped]
        except ImportError:
            self._print_error(
                "sounddevice not installed.\n"
                "Install: pip install sounddevice"
            )
            return

        self._print_status("Recording... (speak now)")

        def audio_callback(
            indata: bytes,
            frames: int,
            _time_info: object,
            _status: object,
        ) -> None:
            """Callback for sounddevice InputStream."""
            if self._running:
                # Schedule send in the event loop
                asyncio.run_coroutine_threadsafe(
                    self._send_audio(ws, indata.tobytes()),
                    asyncio.get_event_loop(),
                )

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=self.device,
            blocksize=CHUNK_BYTES // 2,
            callback=audio_callback,
        )

        with stream:
            while self._running:
                await asyncio.sleep(0.1)

    async def _send_audio(self, ws: Any, chunk: bytes) -> None:
        """Send an audio chunk to the server."""
        if not chunk:
            return
        try:
            await ws.send(chunk)
            self.stats.total_audio_sent += len(chunk)
        except Exception as e:
            print(f"  Send error: {e}", file=sys.stderr)  # noqa: T201

    async def _receive_messages(self, ws: Any) -> None:
        """Receive and process messages from the server."""
        while self._running:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            if isinstance(message, bytes):
                # Audio chunk from TTS
                self.stats.audio_chunks_received += 1
                await self._play_audio(message)
            elif isinstance(message, str):
                await self._handle_json(message)

    async def _handle_json(self, raw: str) -> None:
        """Handle a JSON message from the server."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")

        if msg_type == "connected":
            pass  # Already handled

        elif msg_type == "vad.speech_start":
            self._print_status("🎤 Speaking...")

        elif msg_type == "transcript.partial":
            text = data.get("text", "")
            self.stats.last_partial_text = text
            self.stats.partials_received += 1
            self._clear_line()
            self._print_inline(f"📝 {text}", end="\r")

        elif msg_type == "vad.speech_end":
            silence_ms = data.get("silence_duration_ms", 0)
            self._clear_line()
            self._print_status(
                f"Silence detected ({silence_ms}ms). Processing..."
            )

        elif msg_type == "transcript.final":
            text = data.get("text", "")
            self._clear_line()
            self._print_status(f"✅ You said: {text}")

        elif msg_type == "llm.token":
            token = data.get("token", "")
            self.stats.tokens_received += 1
            self._print_inline(token, end="")
            sys.stdout.flush()

        elif msg_type == "llm.complete":
            text = data.get("text", "")
            self.stats.responses.append(text)
            print()  # noqa: T201
            self._print_status("🔊 Generating speech...")

        elif msg_type == "tts.start":
            total_bytes = data.get("bytes", 0)
            self._print_status(
                f"🔊 Playing response ({total_bytes // 3200 * 200}ms)..."
            )

        elif msg_type == "tts.chunk":
            pass  # Audio binary follows

        elif msg_type == "tts.complete":
            self._print_status("🎤 Listening... (speak now)")

        elif msg_type == "heartbeat":
            pass  # Silent keepalive

        elif msg_type == "error":
            self._print_error(data.get("message", "Unknown error"))

        elif msg_type == "cancelled":
            self._print_status("Cancelled")

    async def _play_audio(self, audio_chunk: bytes) -> None:
        """Play an audio chunk from TTS."""
        try:
            import numpy as np  # type: ignore[import-untyped]
            import sounddevice as sd  # type: ignore[import-untyped]
        except ImportError:
            return

        try:
            samples = np.frombuffer(audio_chunk, dtype=np.int16)
            sd.play(samples, samplerate=SAMPLE_RATE)
        except Exception as e:
            print(f"  Playback error: {e}", file=sys.stderr)  # noqa: T201

    def _print_status(self, msg: str) -> None:
        """Print a status message."""
        print(f"\n  {msg}")  # noqa: T201

    def _print_error(self, msg: str) -> None:
        """Print an error message."""
        print(f"\n  ❌ Error: {msg}", file=sys.stderr)  # noqa: T201

    def _print_inline(self, msg: str, end: str = "") -> None:
        """Print inline without newline."""
        print(msg, end=end)  # noqa: T201

    def _clear_line(self) -> None:
        """Clear the current terminal line."""
        print("\r\033[K", end="")  # noqa: T201

    def _print_help(self) -> None:
        """Print usage hints."""
        print(  # noqa: T201
            "\n  Commands:"
            "\n    Speak naturally — audio is streamed continuously"
            "\n    Press Ctrl+C to exit"
        )

    def _print_stats(self) -> None:
        """Print session statistics."""
        elapsed = time.time() - self.stats.start_time
        print("\n" + "=" * 40)  # noqa: T201
        print("  Session Statistics:")  # noqa: T201
        print(f"    Duration: {elapsed:.1f}s")  # noqa: T201
        print(  # noqa: T201
            f"    Audio sent: {self.stats.total_audio_sent / 1024:.1f} KB"
        )
        print(  # noqa: T201
            f"    Partials: {self.stats.partials_received}"
        )
        print(f"    LLM tokens: {self.stats.tokens_received}")  # noqa: T201
        print(  # noqa: T201
            f"    Audio chunks: {self.stats.audio_chunks_received}"
        )
        print(f"    Responses: {len(self.stats.responses)}")  # noqa: T201
        print("=" * 40)  # noqa: T201


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="J.A.R.V.I.S. Streaming Voice Client"
    )
    parser.add_argument(
        "--url",
        default="ws://localhost:8000/ws/audio",
        help="WebSocket URL (default: ws://localhost:8000/ws/audio)",
    )
    parser.add_argument(
        "--api-key",
        help="API key for authentication",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Sounddevice input device index",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Disable VAD (use manual stop with Ctrl+C)",
    )
    args = parser.parse_args()

    client = StreamingClient(
        url=args.url,
        api_key=args.api_key,
        device=args.device,
        vad_enabled=not args.no_vad,
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        client._print_status("\nExiting...")
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
