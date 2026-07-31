#!/usr/bin/env python3
"""Real-time CLI client for J.A.R.V.I.S. using FSM protocol messages.

Connects to the orchestrator's /ws/audio endpoint, streams microphone
audio, and handles all FSM protocol messages with inline display.

Usage:
    python cli_realtime.py
    python cli_realtime.py --host localhost --port 8000
    python cli_realtime.py --api-key my-secret-key --device 0
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import sys
import threading
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
FRAME_DURATION_MS = 100
FRAME_SIZE = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * FRAME_DURATION_MS // 1000
FRAMES_PER_BLOCK = FRAME_SIZE // SAMPLE_WIDTH


class RealtimeCLI:
    """Real-time CLI client for J.A.R.V.I.S. FSM-based voice streaming."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        api_key: str | None = None,
        device: int | None = None,
    ) -> None:
        self._ws_url = f"ws://{host}:{port}/ws/audio"
        self._api_key = api_key
        self._device = device
        self._running = False
        self._session_id = ""
        self._ws: Any = None

        self._interrupt_count = 0
        self._cancel_requested = False

        self._playback_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._playback_stream: Any = None

        self._partial_text = ""
        self._handlers: dict[str, Any] = {
            "vad.speech_start": self._on_speech_start,
            "transcript.partial": self._on_partial,
            "vad.speech_end": self._on_speech_end,
            "transcript.final": self._on_final,
            "llm.token": self._on_llm_token,
            "llm.complete": self._on_llm_complete,
            "tts.start": self._on_tts_start,
            "tts.complete": self._on_tts_complete,
            "interrupted": self._on_interrupted,
            "listening.timeout": self._on_timeout,
            "cancelled": self._on_cancelled,
            "error": self._on_error,
        }

    async def run(self) -> None:
        import websockets

        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        self._init_playback()
        self._setup_signals()

        try:
            async with websockets.connect(
                self._ws_url,
                additional_headers=headers,
                max_size=2**25,
            ) as ws:
                self._ws = ws
                self._running = True

                msg = await ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "connected":
                        self._session_id = data["session_id"]
                        self._print_status(f"Connected! Session: {self._session_id}")
                        self._print_help()
                    elif data.get("type") == "error":
                        self._print_error(data.get("message", "Unknown error"))
                        return

                await self._handle_session(ws)

        except websockets.exceptions.ConnectionClosed:
            self._print_status("Connection closed")
        except OSError as e:
            self._print_error(f"Connection error: {e}")
        except Exception as e:
            self._print_error(f"Unexpected error: {e}")
        finally:
            self._running = False
            self._ws = None
            if self._playback_stream:
                with contextlib.suppress(Exception):
                    self._playback_stream.stop()
                    self._playback_stream.close()
            print()

    def _setup_signals(self) -> None:
        loop = asyncio.get_event_loop()

        def _on_sigint() -> None:
            self._cancel_requested = True
            self._interrupt_count += 1
            if self._interrupt_count >= 3:
                print("\n  Force quitting...")
                sys.exit(1)

        try:
            loop.add_signal_handler(signal.SIGINT, _on_sigint)
        except NotImplementedError:
            signal.signal(signal.SIGINT, lambda _sig, _frame: _on_sigint())

    def _init_playback(self) -> None:
        import sounddevice as sd

        def callback(
            outdata: np.ndarray,
            frames: int,
            _time_info: object,
            _status: object,
        ) -> None:
            needed = frames * SAMPLE_WIDTH
            with self._buffer_lock:
                available = len(self._playback_buffer)
                if available >= needed:
                    outdata[:] = np.frombuffer(
                        self._playback_buffer[:needed], dtype=np.int16
                    ).reshape(-1, 1)
                    del self._playback_buffer[:needed]
                elif available > 0:
                    samples = available // SAMPLE_WIDTH
                    outdata[:samples] = np.frombuffer(
                        self._playback_buffer, dtype=np.int16
                    ).reshape(-1, 1)
                    outdata[samples:] = 0
                    self._playback_buffer.clear()
                else:
                    outdata.fill(0)

        self._playback_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
            blocksize=FRAMES_PER_BLOCK,
            device=self._device,
        )
        self._playback_stream.start()

    async def _handle_session(self, ws: Any) -> None:
        audio_task = asyncio.create_task(self._capture_audio(ws))
        stdin_task = asyncio.create_task(self._read_stdin(ws))
        receiver_task = asyncio.create_task(self._receive_messages(ws))

        done, pending = await asyncio.wait(
            [audio_task, stdin_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        for task in done:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    exc = task.exception()
                    if exc:
                        self._print_error(str(exc))

    async def _capture_audio(self, ws: Any) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            self._print_error("sounddevice not installed.\nInstall: pip install sounddevice")
            return

        def audio_callback(
            indata: np.ndarray,
            frames: int,
            _time_info: object,
            _status: object,
        ) -> None:
            if self._running:
                asyncio.run_coroutine_threadsafe(
                    self._send_audio(ws, indata.tobytes()),
                    asyncio.get_event_loop(),
                )

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=self._device,
            blocksize=FRAMES_PER_BLOCK,
            callback=audio_callback,
        )

        with stream:
            while self._running:
                await asyncio.sleep(0.1)

    async def _send_audio(self, ws: Any, chunk: bytes) -> None:
        if not chunk:
            return
        try:
            await ws.send(chunk)
        except Exception:
            pass

    async def _read_stdin(self, ws: Any) -> None:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self._running:
            if self._cancel_requested:
                self._cancel_requested = False
                await self._send_json(ws, {"type": "cancel"})

            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.3)
            except asyncio.TimeoutError:
                continue

            if not line:
                break

            cmd = line.decode().strip().lower()

            if cmd == "/quit":
                self._running = False
                break
            if cmd == "":
                await self._send_json(ws, {"type": "stop"})
            elif cmd == "/cancel":
                await self._send_json(ws, {"type": "cancel"})
            elif cmd == "/config":
                self._print_status(
                    f"Host: {self._ws_url} | Session: {self._session_id}"
                )

    async def _send_json(self, ws: Any, data: dict) -> None:
        try:
            await ws.send(json.dumps(data))
        except Exception:
            pass

    async def _receive_messages(self, ws: Any) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            if isinstance(message, bytes):
                self._queue_playback(message)
            elif isinstance(message, str):
                await self._handle_message(message)

    def _queue_playback(self, audio_data: bytes) -> None:
        with self._buffer_lock:
            self._playback_buffer.extend(audio_data)

    async def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")

        handler = self._handlers.get(msg_type)
        if handler is not None:
            await handler(data)

    async def _on_speech_start(self, _data: dict[str, Any]) -> None:
        self._clear_partial()
        self._print_status("🎤 Listening...")

    async def _on_partial(self, data: dict[str, Any]) -> None:
        text = data.get("text", "")
        self._partial_text = text
        self._clear_line()
        self._print_inline(f"📝 {text}", end="\r")

    async def _on_speech_end(self, data: dict[str, Any]) -> None:
        silence_ms = data.get("silence_duration_ms", 0)
        self._clear_line()
        self._print_status(f"⏳ Processing... ({silence_ms}ms silence)")

    async def _on_final(self, data: dict[str, Any]) -> None:
        text = data.get("text", "")
        self._clear_line()
        if text:
            self._print_status(f"📝 You: {text}")

    async def _on_llm_token(self, data: dict[str, Any]) -> None:
        token = data.get("token", "")
        self._print_inline(token, end="")
        sys.stdout.flush()

    async def _on_llm_complete(self, data: dict[str, Any]) -> None:
        text = data.get("text", "")
        print()
        if text:
            self._print_status(f"🤖 JARVIS: {text}")

    async def _on_tts_start(self, data: dict[str, Any]) -> None:
        total_bytes = data.get("bytes", 0)
        duration_ms = total_bytes // 32
        self._print_status(f"🔊 Speaking... ({duration_ms}ms)")

    async def _on_tts_complete(self, _data: dict[str, Any]) -> None:
        self._print_status("Done")

    async def _on_interrupted(self, _data: dict[str, Any]) -> None:
        self._print_status("⏹ Interrupted")

    async def _on_timeout(self, _data: dict[str, Any]) -> None:
        self._print_status("⏰ Listening timed out")

    async def _on_cancelled(self, _data: dict[str, Any]) -> None:
        self._print_status("Cancelled")

    async def _on_error(self, data: dict[str, Any]) -> None:
        self._print_error(data.get("message", "Unknown error"))

    def _clear_partial(self) -> None:
        if self._partial_text:
            self._clear_line()
            self._partial_text = ""

    def _print_status(self, msg: str) -> None:
        print(f"\n  {msg}")

    def _print_error(self, msg: str) -> None:
        print(f"\n  ❌ Error: {msg}", file=sys.stderr)

    def _print_inline(self, msg: str, end: str = "") -> None:
        print(msg, end=end)

    def _clear_line(self) -> None:
        print("\r\033[K", end="")

    def _print_help(self) -> None:
        print(
            "\n  Commands:"
            "\n    Press Enter to stop listening"
            "\n    Type /cancel to cancel"
            "\n    Type /quit to exit"
            "\n    Type /config to show settings"
            "\n    Press Ctrl+C to cancel"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="J.A.R.V.I.S. Real-time CLI Client"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
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
    args = parser.parse_args()

    client = RealtimeCLI(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
        device=args.device,
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
