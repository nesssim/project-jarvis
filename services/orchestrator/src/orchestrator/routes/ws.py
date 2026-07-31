from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from shared.logging import get_logger
from shared.state import FSMState

from orchestrator.core.pipeline import RealtimePipeline

logger = get_logger("orchestrator.ws")

router = APIRouter()

MIN_TRANSCRIBE_BYTES = 160
PARTIAL_INTERVAL = 0.6
VAD_CHECK_INTERVAL = 0.15
HEARTBEAT_INTERVAL = 5.0

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

MAX_WS_BINARY_SIZE = 10 * 1024 * 1024
MAX_WS_TEXT_SIZE = 65536
MAX_CONNECTIONS = 10

_active_connections: dict[str, WebSocket] = {}
_connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)


async def _send_json(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        logger.debug("failed to send json (client may be gone)")


async def _send_audio_chunk(
    ws: WebSocket, chunk: bytes, is_final: bool
) -> None:
    try:
        await ws.send_bytes(chunk)
        await _send_json(ws, {
            "type": "audio.chunk_sent",
            "bytes": len(chunk),
            "is_final": is_final,
        })
    except Exception:
        logger.debug("failed to send audio (client may be gone)")


async def _audio_sender(
    ws: WebSocket,
    pipeline: RealtimePipeline,
) -> None:
    try:
        while True:
            chunk = await pipeline._tts_output_queue.get()
            if chunk is None:
                break
            await _send_audio_chunk(ws, chunk.data, chunk.is_final)
    except Exception:
        logger.debug("audio sender task exited")


async def _listening_timeout(
    pipeline: RealtimePipeline,
    timeout_seconds: int,
) -> None:
    await asyncio.sleep(timeout_seconds)
    if pipeline.fsm.state == FSMState.LISTENING:
        await pipeline.handle_timeout()


@router.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket):
    async with _connection_semaphore:
        await websocket.accept()

        settings = websocket.app.state.settings

        api_key = websocket.headers.get(settings.auth.api_key_header, "")
        if settings.auth.enabled and api_key != settings.auth.api_key:
            logger.warning(
                "ws auth rejected",
                header=settings.auth.api_key_header,
            )
            await websocket.close(code=4001)
            return

        session_id = uuid.uuid4().hex[:12]
        _active_connections[session_id] = websocket

        stt = websocket.app.state.stt_client
        tts = websocket.app.state.tts_client
        llm = websocket.app.state.llm_client
        prompt_mgr = websocket.app.state.prompt_manager

        async def event_callback(msg_type: str, payload: dict) -> None:
            await _send_json(websocket, {
                "type": msg_type,
                **payload,
            })

        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt_mgr,
            settings=settings,
            event_callback=event_callback,
        )
        pipeline.set_session(session_id)

        listening_timer_task: asyncio.Task | None = None
        audio_sender_task: asyncio.Task | None = None

        try:
            await _send_json(websocket, {
                "type": "connected",
                "session_id": session_id,
            })
            logger.info("ws connected", session_id=session_id)

            _vad_session: str | None = None
            last_heartbeat_time = time.monotonic()

            while True:
                now = time.monotonic()
                if now - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    last_heartbeat_time = now
                    try:
                        await _send_json(websocket, {
                            "type": "heartbeat",
                            "timestamp": now,
                        })
                    except Exception:
                        break

                try:
                    message = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=HEARTBEAT_INTERVAL,
                    )

                    if "bytes" in message and len(message["bytes"]) > MAX_WS_BINARY_SIZE:
                        logger.warning(
                            "binary message too large",
                            session_id=session_id,
                            bytes=len(message["bytes"]),
                        )
                        await _send_json(websocket, {
                            "type": "error",
                            "message": f"Binary message exceeds {MAX_WS_BINARY_SIZE} bytes",
                        })
                        continue

                    if "text" in message and len(message["text"]) > MAX_WS_TEXT_SIZE:
                        logger.warning(
                            "text message too large",
                            session_id=session_id,
                            bytes=len(message["text"]),
                        )
                        await _send_json(websocket, {
                            "type": "error",
                            "message": f"Text message exceeds {MAX_WS_TEXT_SIZE} bytes",
                        })
                        continue

                except asyncio.TimeoutError:
                    if (pipeline.fsm.state == FSMState.LISTENING
                        and listening_timer_task is not None
                        and listening_timer_task.done()):
                        await pipeline.handle_timeout()
                    continue
                except WebSocketDisconnect:
                    logger.info("ws disconnected", session_id=session_id)
                    break
                except RuntimeError as e:
                    if "disconnect" in str(e).lower():
                        logger.info("ws disconnected", session_id=session_id)
                        break
                    raise

                if message.get("type") == "websocket.receive" and "text" in message:
                    try:
                        control = json.loads(message["text"])
                    except json.JSONDecodeError:
                        logger.warning("invalid json", session_id=session_id)
                        continue

                    cmd = control.get("type", "")

                    if cmd == "config":
                        logger.debug("client config", session_id=session_id, **control)

                    elif cmd == "stop":
                        if pipeline.fsm.state == FSMState.LISTENING:
                            await _send_json(websocket, {
                                "type": "vad.speech_end",
                                "silence_duration_ms": 0,
                            })
                            if listening_timer_task and not listening_timer_task.done():
                                listening_timer_task.cancel()
                            await pipeline.handle_speech_end()

                    elif cmd == "cancel":
                        logger.debug("cancel requested", session_id=session_id)
                        if audio_sender_task and not audio_sender_task.done():
                            audio_sender_task.cancel()
                        await pipeline.handle_cancel()
                        pipeline.reset_buffer()
                        await stt.reset_vad(session_id=session_id)
                        await _send_json(websocket, {"type": "cancelled"})

                elif message.get("type") == "websocket.receive" and "bytes" in message:
                    audio_chunk: bytes = message["bytes"]
                    if not audio_chunk:
                        continue

                    state = pipeline.fsm.state

                    if state == FSMState.IDLE:
                        try:
                            vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                        except Exception as e:
                            logger.warning("vad check failed", session_id=session_id, error=str(e))
                            continue

                        if vad_result.get("is_speech", False):
                            await pipeline.push_audio(audio_chunk)
                            await pipeline.fsm.transition(
                                FSMState.LISTENING, reason="vad_speech_start"
                            )
                            await _send_json(websocket, {
                                "type": "vad.speech_start",
                                "timestamp": time.time(),
                            })
                            if listening_timer_task is not None and not listening_timer_task.done():
                                listening_timer_task.cancel()
                                try:
                                    await listening_timer_task
                                except asyncio.CancelledError:
                                    pass
                            listening_timer_task = asyncio.create_task(
                                _listening_timeout(pipeline, settings.listening.timeout_seconds)
                            )
                            if audio_sender_task is not None and not audio_sender_task.done():
                                audio_sender_task.cancel()
                                try:
                                    await audio_sender_task
                                except asyncio.CancelledError:
                                    pass
                            audio_sender_task = asyncio.create_task(
                                _audio_sender(websocket, pipeline)
                            )

                    elif state == FSMState.LISTENING:
                        await pipeline.push_audio(audio_chunk)

                        try:
                            vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                        except Exception as e:
                            logger.warning("vad check failed", session_id=session_id, error=str(e))
                            continue

                        if not vad_result.get("is_speech", True):
                            silence_ms = vad_result.get("silence_duration_ms", 0)
                            if silence_ms >= settings.listening.silence_threshold_ms:
                                await _send_json(websocket, {
                                    "type": "vad.speech_end",
                                    "silence_duration_ms": silence_ms,
                                })
                                if listening_timer_task and not listening_timer_task.done():
                                    listening_timer_task.cancel()
                                await pipeline.handle_speech_end()

                    elif state in (FSMState.PROCESSING, FSMState.SPEAKING):
                        if settings.listening.barge_in_enabled:
                            try:
                                vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                            except Exception:
                                logger.warning("barge-in vad check failed", session_id=session_id)
                                continue

                            if vad_result.get("is_speech", False):
                                await pipeline.handle_barge_in()
                                await _send_json(websocket, {"type": "interrupted"})
                                await pipeline.push_audio(audio_chunk)
                                await _send_json(websocket, {
                                    "type": "vad.speech_start",
                                    "timestamp": time.time(),
                                })

                    elif state == FSMState.INTERRUPTED:
                        await pipeline.push_audio(audio_chunk)

                    elif state == FSMState.TOOL_WAITING:
                        if settings.listening.barge_in_enabled:
                            pipeline.push_audio(audio_chunk)

                    elif state == FSMState.ERROR:
                        pass

            logger.info("ws cleanup", session_id=session_id)
            await pipeline.handle_cancel()

        except WebSocketDisconnect:
            logger.info("ws disconnected", session_id=session_id)
        except RuntimeError as e:
            if "disconnect" in str(e).lower():
                logger.info("ws disconnected (runtime)", session_id=session_id)
            else:
                logger.exception("ws runtime error", session_id=session_id)
        except Exception:
            logger.exception("ws error", session_id=session_id)
            try:
                await _send_json(websocket, {"type": "error", "message": "Internal server error"})
            except Exception:
                logger.warning("failed to send error message", session_id=session_id)
        finally:
            _active_connections.pop(session_id, None)
            if audio_sender_task is not None and not audio_sender_task.done():
                audio_sender_task.cancel()
            if listening_timer_task is not None and not listening_timer_task.done():
                listening_timer_task.cancel()
            try:
                await stt.reset_vad(session_id=session_id)
            except Exception:
                logger.debug("failed to reset vad during cleanup", session_id=session_id)
