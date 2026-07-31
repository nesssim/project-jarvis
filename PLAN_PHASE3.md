# Phase 3 Execution Plan: Real-Time Conversation Pipeline

## Overview

Transform JARVIS from sequential "walkie-talkie" (STT→LLM→TTS one at a time) to a concurrent, FSM-driven real-time conversation with barge-in capability. This plan covers the **core architectural changes** — approximately 26h of work delivered across **6 parallelizable batches** (11 files).

## Scope

| Batch | What | Files | Risk | Est. Time |
|-------|------|-------|------|-----------|
| 0 | Foundation (parallel leaf files) | 4 new/amend | Low | 2h |
| 1 | StateMachine class | 1 new | Medium | 4h |
| 2 | Sentence-chunked TTS | 1 new | Low | 2h |
| 3 | Concurrent pipeline rewrite | 1 rewrite | **High** | 8h |
| 4 | FSM-driven WS handler + barge-in | 1 rewrite, 1 amend | **High** | 6h |
| 5 | FSM unit tests + config wiring + old test fix | 3 files | Medium | 4h |
| **Total** | **6 batches** | **11 files** | | **~26h** |

### Deferred
- Wake word (openWakeWord integration) — full new feature
- Groq LLM client — switchable LLM provider
- Sliding conversation buffer (prompt.py with turn history)
- Real-time CLI client (cli_realtime.py)
- Barge-in tuning script (scripts/tune_barge_in.py)
- Latency regression tests (tests/test_latency.py)
- Full integration test suite (tests/test_realtime_stream.py)

---

## Dependency Graph

```
Batch 0a (state.py)       Batch 0b (chunker.py)     Batch 0c (config.py)    Batch 0d (settings.yaml)
       │                         │                        │                        │
       │                         │                        │                        │
       ▼                         │                        ▼                        ▼
Batch 1 (state_machine.py)      │              (amended config models)
       │                         │
       │                         ▼
       ▼               Batch 2 (chunker.py full impl)
Batch 3 (pipeline.py rewrite) ◄─┘
       │
       ▼
Batch 4 (ws.py rewrite + main.py amend)
       │
       ▼
Batch 5 (tests + fixture updates)
```

**Critical path:** 0a → 1 → 3 → 4 → 5 (5 sequential steps, ~20h)

**Parallelizable:** 0b and 0c/0d can run in parallel with 0a/1; 2 can run in parallel with 1; 5 can start after 3.

---

## Batch 0: Foundation

### Batch 0a — FSMState Enum
**File:** `shared/src/shared/state.py` (NEW)

**Implementation:**
- `FSMState(str, Enum)` with 7 states: `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `INTERRUPTED`, `TOOL_WAITING`, `ERROR`
- `TRANSITIONS` dict: `dict[tuple[FSMState, FSMState], str]` with ~20 core transitions (see below)
- `AUDIO_INPUT_STATES: frozenset[FSMState]` — states where audio input is accepted
- `INTERRUPTIBLE_STATES: frozenset[FSMState]` — states where barge-in can occur
- `SILENT_STATES: frozenset[FSMState]` — states where TTS output is silenced
- `VALID_STATES` classmethod for validation

**Core transitions:**
| From | To | Reason |
|------|----|--------|
| IDLE | LISTENING | vad_speech_start |
| IDLE | ERROR | internal_error |
| LISTENING | PROCESSING | vad_speech_end |
| LISTENING | ERROR | stt_failure |
| PROCESSING | SPEAKING | tts_ready |
| PROCESSING | TOOL_WAITING | tool_call |
| PROCESSING | INTERRUPTED | user_interrupt |
| PROCESSING | ERROR | llm_failure |
| SPEAKING | IDLE | tts_complete |
| SPEAKING | INTERRUPTED | barge_in |
| SPEAKING | ERROR | tts_failure |
| INTERRUPTED | LISTENING | resume_listening |
| INTERRUPTED | ERROR | interrupt_timeout |
| TOOL_WAITING | PROCESSING | tool_result_ready |
| TOOL_WAITING | ERROR | tool_failure |
| ERROR | IDLE | recovery_timeout |

**Dependencies:** None (pure Python stdlib)
**Tests:** Verify enum values, transitions dict entry count, set membership checks

---

### Batch 0b — TTS Sentence Chunker (interface)
**File:** `services/tts/src/tts/chunker.py` (NEW)

**Class `SentenceChunker`:**
- Constructor: `__init__(self, min_chars=15, max_chars=300)`
- `async add_token(token: str) -> AsyncIterator[str]` — accumulates tokens, yields complete sentences
- `async flush() -> AsyncIterator[str]` — yields remaining buffer
- `is_empty -> bool` property

**Sentence boundary detection:**
```python
SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z\"'«»„])"   # Period + space + capital letter
    r"|(?<=[.!?])(?=\Z)"                # Period at end of text
)
```

**Edge cases handled:**
- Abbreviations ("Dr.", "Mr.", "U.S.") — check lowercase after period heuristic
- Force break at `max_chars` if no sentence boundary found
- Empty token / whitespace-only token: skip silently
- Very short sentences (< `min_chars`): wait for more context before emitting

**Dependencies:** None (pure Python)
**Note:** Only the interface and implementation skeleton is created here. The full implementation is in Batch 2.

---

### Batch 0c — Config Additions
**File:** `shared/src/shared/config.py` (AMEND)

**Add these model classes before `Settings`:**

```python
class WakeWordConfig(BaseModel):
    enabled: bool = False
    model_path: str = "/models/wake-word"
    sensitivity: float = 0.5
    vad_cooldown_ms: int = 2000
```

**Extend `ListeningConfig`:**
- Add fields: `max_utterance_seconds: int = 30`, `barge_in_enabled: bool = True`, `barge_in_jitter_ms: int = 200`

**Add to `Settings`:**
- `wake_word: WakeWordConfig = WakeWordConfig()` field

**Dependencies:** None (pure Pydantic)

---

### Batch 0d — Settings YAML
**File:** `config/settings.yaml` (AMEND)

**Add/update sections:**
```yaml
listening:
  timeout_seconds: 5
  silence_threshold_ms: 800
  max_utterance_seconds: 30
  barge_in_enabled: true
  barge_in_jitter_ms: 200

wake_word:
  enabled: false
  model_path: "/models/wake-word"
  sensitivity: 0.5
  vad_cooldown_ms: 2000
```

---

## Batch 1: StateMachine Class

### File: `services/orchestrator/src/orchestrator/core/state_machine.py` (NEW)

**Class `StateMachine`:**
- **Constructor:** `__init__(self, initial_state=FSMState.IDLE, on_transition=Optional[Callable])`
- **State tracking:** `_state` (FSMState), `_lock` (asyncio.Lock), `_state_enter_time`, `_consecutive_errors`
- **Read-only properties:** `state`, `state_duration_ms`, `can_accept_audio`, `is_interruptible`, `consecutive_errors`

**Key methods:**

```python
async def transition(self, target: FSMState, reason: str = "") -> bool:
    """Validate and execute a state transition.
    
    - Acquires lock
    - Validates (self._state, target) exists in TRANSITIONS
    - Calls on_exit callbacks for old state
    - Updates _state
    - Calls on_enter callbacks for new state 
    - Calls self._on_transition(old, new, reason)
    - Updates _state_enter_time
    - Returns True on success
    - Raises TransitionError if invalid
    """

async def force_state(self, target: FSMState, reason: str = "") -> None:
    """Force transition without validation (for ERROR recovery)."""

async def reset(self) -> None:
    """Reset to IDLE with error count cleared."""

def on_enter(self, state: FSMState) -> Callable[[], Awaitable[None]] | None:
    """Decorator to register an enter callback for a state."""
    
def on_exit(self, state: FSMState) -> Callable[[], Awaitable[None]] | None:
    """Decorator to register an exit callback for a state."""

async def request_barge_in(self) -> bool:
    """Request barge-in. Only valid from INTERRUPTIBLE_STATES."""
```

**Error tracking:**
- `_consecutive_errors` increments on ERROR entry
- Resets to 0 on successful transition out of ERROR
- `should_auto_recover() -> bool` returns True if `consecutive_errors < 3`

**Behavior of `TransitionError`:**
- Exception class with `source` (current state), `target` (requested), `valid_targets` (list)
- Message: `"Cannot transition from LISTENING to SPEAKING. Valid targets: PROCESSING, ERROR"`

**Testing:**
```python
# test_fsm.py
def test_valid_transition():
    fsm = StateMachine()
    result = await fsm.transition(FSMState.LISTENING, reason="vad_speech_start")
    assert result is True
    assert fsm.state == FSMState.LISTENING

def test_invalid_transition_raises():
    fsm = StateMachine()
    with pytest.raises(TransitionError):
        await fsm.transition(FSMState.SPEAKING, reason="invalid")

def test_barge_in_only_from_interruptible():
    fsm = StateMachine(FSMState.IDLE)
    assert await fsm.request_barge_in() is False
    await fsm.force_state(FSMState.SPEAKING)
    assert await fsm.request_barge_in() is True

def test_concurrent_transitions_serialized():
    fsm = StateMachine()
    async def t1(): await fsm.transition(FSMState.LISTENING)
    async def t2(): await fsm.transition(FSMState.LISTENING)
    # Run concurrently, both should succeed
    ...

def test_error_counting():
    fsm = StateMachine()
    await fsm.force_state(FSMState.ERROR)
    assert fsm.consecutive_errors == 1
    await fsm.force_state(FSMState.IDLE)
    await fsm.force_state(FSMState.ERROR)
    assert fsm.consecutive_errors == 2
    await fsm.reset()
    assert fsm.consecutive_errors == 0

def test_triple_failure_guard():
    fsm = StateMachine()
    for _ in range(3):
        await fsm.force_state(FSMState.ERROR)
        assert fsm.consecutive_errors == _ + 1
        await fsm.force_state(FSMState.IDLE)
    await fsm.force_state(FSMState.ERROR)
    assert fsm.should_auto_recover() is False  # Triple failure
```

---

## Batch 2: SentenceChunker Full Implementation

### File: `services/tts/src/tts/chunker.py` (FULL IMPLEMENTATION)
(Interface defined in Batch 0b; this batch completes the logic.)

**Implementation details for `add_token()`:**
```python
async def add_token(self, token: str) -> AsyncIterator[str]:
    if not token:
        return
    self._buffer += token
    
    while len(self._buffer) >= self._min_chars:
        # Try to find a sentence boundary
        match = SENTENCE_BOUNDARY.search(self._buffer)
        if match:
            sentence = self._buffer[:match.end()]
            self._buffer = self._buffer[match.end():]
            yield sentence.strip()
        elif len(self._buffer) >= self._max_chars:
            # Force break at last space
            last_space = self._buffer.rfind(" ", 0, self._max_chars)
            if last_space > 0:
                sentence = self._buffer[:last_space]
                self._buffer = self._buffer[last_space:].lstrip()
                yield sentence.strip()
            else:
                # No space found, hard break at max_chars
                sentence = self._buffer[:self._max_chars]
                self._buffer = self._buffer[self._max_chars:]
                yield sentence.strip()
        else:
            break  # Not enough text for a sentence yet
```

**Tests (in `tests/services/tts/test_chunker.py`):**
```python
@pytest.mark.asyncio
async def test_single_sentence():
    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Hello world."):
        sentences.append(s)
    assert sentences == ["Hello world."]

@pytest.mark.asyncio
async def test_multiple_sentences():
    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Hello. World. Test."):
        sentences.append(s)
    assert sentences == ["Hello.", "World.", "Test."]

@pytest.mark.asyncio
async def test_streaming_tokens():
    chunker = SentenceChunker(min_chars=1)
    sentences = []
    for token in ["The", " weather", " is", " nice", " today.", " Let's", " go", " out."]:
        async for s in chunker.add_token(token):
            sentences.append(s)
    assert len(sentences) == 2
    assert "today." in sentences[0]
    assert "out." in sentences[1]

@pytest.mark.asyncio
async def test_abbreviation_handling():
    chunker = SentenceChunker(min_chars=1)
    sentences = []
    async for s in chunker.add_token("Dr. Smith is here. He came early."):
        sentences.append(s)
    assert len(sentences) == 2

@pytest.mark.asyncio
async def test_flush():
    chunker = SentenceChunker()
    # Buffer some text without sentence boundary
    async for _ in chunker.add_token("Hello world"):
        pass
    flushed = []
    async for s in chunker.flush():
        flushed.append(s)
    assert flushed == ["Hello world"]

@pytest.mark.asyncio
async def test_max_chars_force_break():
    chunker = SentenceChunker(min_chars=50, max_chars=50)
    long_text = "A" * 60 + " B" * 10
    sentences = []
    async for s in chunker.add_token(long_text):
        sentences.append(s)
    assert len(sentences) >= 1
    assert all(len(s) <= 55 for s in sentences)
```

---

## Batch 3: Concurrent Pipeline Rewrite (CRITICAL PATH)

### File: `services/orchestrator/src/orchestrator/core/pipeline.py` (REWRITE)

This is the most complex change. The file keeps all existing exception classes (`PipelineError`, `STTError`, `LLMError`, `TTSError`) and dataclasses (`PipelineResult`, `PartialTranscript`, `LLMToken`, `AudioChunk`), plus `_extract_pcm_from_wav`. The `StreamingPipeline` class is replaced by `RealtimePipeline`.

### `RealtimePipeline` Class Design

```python
class RealtimePipeline:
    """FSM-driven concurrent voice pipeline.
    
    Architecture:
    - Owns a StateMachine instance
    - Accepts audio chunks via push_audio()
    - On speech_end, launches concurrent STT/LLM/TTS tasks via TaskGroup
    - Sentence-chunks LLM output and sends to TTS incrementally
    - Emits events (transcript, token, audio) via event callback
    - Supports barge-in: stops TTS, re-enters LISTENING
    """
    
    def __init__(
        self,
        stt_client: STTClient,
        tts_client: TTSClient,
        llm_client: BaseLLMClient,
        prompt_manager: PromptManager,
        settings: Settings,
        event_callback: Callable[[str, dict], Awaitable[None]] | None = None,
    ):
        self._stt = stt_client
        self._tts = tts_client
        self._llm = llm_client
        self._prompt_manager = prompt_manager
        self._settings = settings
        self._event_callback = event_callback
        
        self._fsm = StateMachine(on_transition=self._on_fsm_transition)
        self._audio_buffer = bytearray()
        self._session_id = ""
        self._cancel_event = asyncio.Event()
        self._tts_output_queue: asyncio.Queue[AudioChunk] = asyncio.Queue()
        self._task_group: asyncio.TaskGroup | None = None
        self._tts_task: asyncio.Task | None = None
        
    # --- Public API ---
    @property
    def fsm(self) -> StateMachine: ...
    
    def set_session(self, session_id: str) -> None: ...
    
    async def push_audio(self, chunk: bytes) -> bool:
        """Feed audio chunk. Returns True if accepted (FSM in AUDIO_INPUT_STATES)."""
        ...
    
    async def handle_speech_end(self) -> None:
        """Triggered by VAD speech_end or client 'stop'. Starts concurrent pipeline."""
        ...
    
    async def handle_barge_in(self) -> None:
        """Triggered by VAD speech_start during SPEAKING/PROCESSING."""
        ...
    
    async def handle_cancel(self) -> None:
        """Cancel all in-flight operations, reset to IDLE."""
        ...
    
    async def handle_timeout(self) -> None:
        """Listening timeout — emit 'I didn't catch that', reset to IDLE."""
        ...
```

### Concurrent Flow for `handle_speech_end()`

```python
async def handle_speech_end(self) -> None:
    """Start the concurrent STT→LLM→TTS pipeline tasks."""
    await self._emit(MessageType.TRANSCRIPT_FINAL.value, {
        "text": "...", "confidence": 0.0,
    })
    
    # 1. Transition FSM to PROCESSING
    await self._fsm.transition(FSMState.PROCESSING, reason="vad_speech_end")
    
    # 2. Get the buffered audio
    audio_data = bytes(self._audio_buffer)
    self._audio_buffer.clear()
    
    # 3. Run STT → LLM → TTS as concurrent pipeline
    async with asyncio.TaskGroup() as tg:
        # STT task
        stt_result = await self._run_stt(audio_data)
        
        # LLM streaming → sentence chunking → TTS
        self._tts_task = tg.create_task(
            self._run_llm_and_tts(stt_result.transcript)
        )
        
        # Barge-in monitor (runs during PROCESSING/SPEAKING)
        tg.create_task(self._monitor_barge_in())
```

### Key Internal Methods

**`_run_stt(audio_data)`:**
- Simple: call `self._stt.transcribe(audio_data)`
- On success: emit `transcript.final`, return result
- On failure: transition to ERROR, emit error event

**`_run_llm_and_tts(transcript)`:**
```python
async def _run_llm_and_tts(self, transcript: str) -> None:
    """Stream LLM tokens through sentence chunker to TTS."""
    chunker = SentenceChunker()
    response_parts: list[str] = []
    
    # Start LLM streaming
    async for llm_token in self._llm.generate(messages):
        if self._cancel_event.is_set():
            return
        
        response_parts.append(llm_token)
        await self._emit(MessageType.LLM_TOKEN.value, {"token": llm_token})
        
        # Feed to sentence chunker
        async for sentence in chunker.add_token(llm_token):
            if sentence.strip():
                await self._synthesize_sentence(sentence)
    
    # Flush remaining text
    async for sentence in chunker.flush():
        if sentence.strip():
            await self._synthesize_sentence(sentence)
    
    response_text = "".join(response_parts)
    await self._emit(MessageType.LLM_COMPLETE.value, {"text": response_text})
```

**`_synthesize_sentence(sentence)`:**
```python
async def _synthesize_sentence(self, sentence: str) -> None:
    """Synthesize a single sentence and stream audio."""
    try:
        audio_bytes = await self._tts.synthesize(sentence)
    except Exception as e:
        await self._fsm.transition(FSMState.ERROR, reason="tts_failure")
        return
    
    raw_pcm = _extract_pcm_from_wav(audio_bytes)
    if not raw_pcm:
        return
    
    # Transition to SPEAKING on first sentence
    if self._fsm.state == FSMState.PROCESSING:
        await self._fsm.transition(FSMState.SPEAKING, reason="tts_ready")
        await self._emit(MessageType.TTS_START.value, {"bytes": len(raw_pcm)})
    
    # Stream in 200ms chunks
    frame_size = (
        self._settings.audio.channels * self._settings.audio.sample_width
    )
    chunk_bytes = max(frame_size, 
        self._settings.audio.sample_rate * frame_size * 200 // 1000
    )
    
    offset = 0
    while offset < len(raw_pcm):
        if self._cancel_event.is_set() or self._fsm.state == FSMState.INTERRUPTED:
            return  # Barge-in or cancel
        end = offset + chunk_bytes
        chunk = raw_pcm[offset:end]
        is_final = (end >= len(raw_pcm))
        await self._emit(MessageType.TTS_AUDIO_CHUNK.value, {
            "bytes": len(chunk), "is_final": is_final,
        })
        yield AudioChunk(data=chunk, is_final=is_final)  # To callback
        offset = end
        await asyncio.sleep(0)  # Yield to event loop
    
    # If this was the last sentence, transition to IDLE
    if self._fsm.state == FSMState.SPEAKING:
        await self._fsm.transition(FSMState.IDLE, reason="tts_complete")
        await self._emit(MessageType.TTS_COMPLETE.value, {"bytes": len(raw_pcm)})
```

**`_monitor_barge_in()`:**
```python
async def _monitor_barge_in(self) -> None:
    """Monitor for barge-in during PROCESSING/SPEAKING.
    
    The WS handler signals barge-in by calling handle_barge_in().
    This task polls the FSM state and manages cancellation.
    """
    while self._fsm.state in (FSMState.PROCESSING, FSMState.SPEAKING):
        await asyncio.sleep(0.05)  # Poll every 50ms
        if self._fsm.state == FSMState.INTERRUPTED:
            # Cancel in-flight TTS
            self._cancel_event.set()
            # Wait for TTS task to stop (with jitter)
            if self._tts_task and not self._tts_task.done():
                await asyncio.wait(
                    [self._tts_task], 
                    timeout=self._settings.listening.barge_in_jitter_ms / 1000
                )
            # Clear output queue
            while not self._tts_output_queue.empty():
                self._tts_output_queue.get_nowait()
            # Transition to LISTENING
            await self._fsm.transition(FSMState.LISTENING, reason="resume_listening")
            self._cancel_event.clear()
            return
```

### WS Handler Integration Contract

The `RealtimePipeline` exposes:
- `fsm: StateMachine` — for querying state
- `push_audio(chunk) -> bool` — returns False if not in AUDIO_INPUT_STATES
- `handle_speech_end()` — starts concurrent pipeline
- `handle_barge_in()` — interrupts TTS output
- `handle_cancel()` — resets everything
- `handle_timeout()` — listening timeout handler

### Compatibility

The old `StreamingPipeline` is removed. Exception classes and dataclasses remain:
- `PipelineError`, `STTError`, `LLMError`, `TTSError`
- `PipelineResult`, `PartialTranscript`, `LLMToken`, `AudioChunk`
- `_extract_pcm_from_wav()` — static utility

This means `test_ws_security.py` needs updates (Batch 5).

---

## Batch 4: WS Handler Rewrite + Barge-in

### File: `services/orchestrator/src/orchestrator/routes/ws.py` (REWRITE)

### Architecture Change

```
Before:  Single while loop with `pipeline_busy` boolean
After:   FSM-driven event loop with state-based dispatch
```

### New Handler Structure

```python
@router.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket):
    """FSM-driven WebSocket handler."""
    async with _connection_semaphore:
        await websocket.accept()
        settings = websocket.app.state.settings
        # ... auth check (unchanged) ...
        
        session_id = uuid.uuid4().hex[:12]
        _active_connections[session_id] = websocket
        
        # Resolve clients (unchanged)
        ...
        
        # Create RealtimePipeline instead of StreamingPipeline
        pipeline = RealtimePipeline(
            stt_client=stt,
            tts_client=tts,
            llm_client=llm,
            prompt_manager=prompt_mgr,
            settings=settings,
            event_callback=lambda t, p: _send_json(websocket, {"type": t, **p}),
        )
        pipeline.set_session(session_id)
        
        try:
            await _send_json(websocket, {
                "type": "connected",
                "session_id": session_id,
            })
            
            last_heartbeat_time = time.monotonic()
            _vad_session = None  # Will hold VAD state
            listening_timer_task = None
            
            while True:
                # --- Heartbeat (periodic send, same as before) ---
                ...
                
                # --- Receive with timeout ---
                try:
                    message = await asyncio.wait_for(
                        websocket.receive(), timeout=HEARTBEAT_INTERVAL,
                    )
                    # Size limit checks (same as before) ...
                except asyncio.TimeoutError:
                    # Check listening timeout
                    if (pipeline.fsm.state == FSMState.LISTENING
                        and listening_timer_task
                        and listening_timer_task.done()):
                        await pipeline.handle_timeout()
                    continue
                except WebSocketDisconnect:
                    break
                
                # --- Route by message type ---
                if "text" in message.get("type", ""):
                    # Parse JSON command
                    ...
                    cmd = control.get("type", "")
                    
                    if cmd == "config":
                        ...  # Same as before
                    
                    elif cmd == "stop":
                        if pipeline.fsm.state in (FSMState.LISTENING,):
                            await pipeline.handle_speech_end()
                    
                    elif cmd == "cancel":
                        await pipeline.handle_cancel()
                        await _send_json(websocket, {"type": "cancelled"})
                
                elif "bytes" in message.get("type", ""):
                    audio_chunk = message["bytes"]
                    if not audio_chunk:
                        continue
                    
                    state = pipeline.fsm.state
                    
                    if state == FSMState.IDLE:
                        # Run VAD to detect speech start
                        vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                        if vad_result.get("is_speech", False):
                            pipeline.push_audio(audio_chunk)
                            await pipeline.fsm.transition(
                                FSMState.LISTENING, reason="vad_speech_start"
                            )
                            await _send_json(websocket, {
                                "type": "vad.speech_start",
                                "timestamp": time.time(),
                            })
                            # Start listening timeout timer
                            listening_timer_task = asyncio.create_task(
                                _listening_timeout(pipeline, settings.listening.timeout_seconds)
                            )
                    
                    elif state == FSMState.LISTENING:
                        # Check VAD for speech end
                        pipeline.push_audio(audio_chunk)
                        vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                        
                        if not vad_result.get("is_speech", True):
                            silence_ms = vad_result.get("silence_duration_ms", 0)
                            if silence_ms >= settings.listening.silence_threshold_ms:
                                # Speech ended
                                await _send_json(websocket, {
                                    "type": "vad.speech_end",
                                    "silence_duration_ms": silence_ms,
                                })
                                # Cancel listening timer
                                if listening_timer_task and not listening_timer_task.done():
                                    listening_timer_task.cancel()
                                await pipeline.handle_speech_end()
                        
                        # Emit partial transcript periodically
                        ...
                    
                    elif state in (FSMState.PROCESSING, FSMState.SPEAKING):
                        # Barge-in: user spoke while we were talking/thinking
                        if settings.listening.barge_in_enabled:
                            vad_result = await stt.check_vad(audio_chunk, session_id=session_id)
                            if vad_result.get("is_speech", False):
                                await pipeline.handle_barge_in()
                                await _send_json(websocket, {
                                    "type": "interrupted",
                                })
                                # Start new listening cycle
                                pipeline.push_audio(audio_chunk)
                                await _send_json(websocket, {
                                    "type": "vad.speech_start",
                                    "timestamp": time.time(),
                                })
                    
                    elif state == FSMState.INTERRUPTED:
                        # Accept audio for the new utterance
                        pipeline.push_audio(audio_chunk)
                    
                    elif state == FSMState.ERROR:
                        # Discard audio while in error state
                        pass
```

### Barge-in Mechanism (inside `RealtimePipeline.handle_barge_in`)

```python
async def handle_barge_in(self) -> None:
    """Handle barge-in during TTS playback or LLM processing."""
    # 1. Signal cancellation for in-flight operations
    self._cancel_event.set()
    
    # 2. Transition through FSM
    await self._fsm.transition(FSMState.INTERRUPTED, reason="barge_in")
    
    # 3. Wait for current TTS chunk to finish (jitter)
    jitter_ms = self._settings.listening.barge_in_jitter_ms
    if self._tts_task and not self._tts_task.done():
        try:
            await asyncio.wait_for(
                asyncio.shield(self._tts_task),
                timeout=jitter_ms / 1000,
            )
        except asyncio.TimeoutError:
            self._tts_task.cancel()
    
    # 4. Clear pending audio
    while not self._tts_output_queue.empty():
        try:
            self._tts_output_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    
    # 5. Reset cancel event for new utterance
    self._cancel_event.clear()
    
    # 6. Transition to LISTENING
    await self._fsm.transition(FSMState.LISTENING, reason="resume_listening")
```

### Listening Timeout

```python
async def _listening_timeout(
    pipeline: RealtimePipeline,
    timeout_seconds: int,
) -> None:
    """Timer task: if no speech detected within timeout, notify user."""
    await asyncio.sleep(timeout_seconds)
    if pipeline.fsm.state == FSMState.LISTENING:
        await pipeline.handle_timeout()
```

Inside `handle_timeout`:
```python
async def handle_timeout(self) -> None:
    """Listening timeout handler."""
    if self._fsm.state != FSMState.LISTENING:
        return
    await self._emit("listening.timeout", {"timeout_seconds": self._settings.listening.timeout_seconds})
    self._audio_buffer.clear()
    await self._fsm.transition(FSMState.IDLE, reason="listening_timeout")
    # Optionally: play a "I didn't catch that" prompt
    # Deferred: will be added in a later iteration
```

### File: `services/orchestrator/src/orchestrator/main.py` (AMEND)

**Add cold-start warmup in `lifespan`:**
```python
async def _warmup_pipeline(settings, llm_client) -> None:
    """Pre-warm the LLM connection by sending a minimal keep-alive request."""
    if settings.llm.provider == "ollama":
        try:
            # Send a minimal request to warm up the model
            async for _ in llm_client.generate(
                messages=[{"role": "user", "content": "Hello"}],
                stream=True,
            ):
                break  # Just need first token
            logger.info("llm warmup complete")
        except Exception as e:
            logger.warning("llm warmup failed (non-fatal)", error=str(e))
```

Call this in `lifespan` after creating the LLM client, using `asyncio.create_task()` so it doesn't block startup.

---

## Batch 5: Tests + Wiring

### File: `tests/test_fsm.py` (NEW) — FSM Unit Tests

**Test classes:**
1. `TestFSMStateEnum` — Verify enum values, transitions set, state group membership
2. `TestStateMachineTransitions` — All valid transitions succeed; invalid ones raise `TransitionError`
3. `TestStateMachineBargeIn` — Barge-in only from INTERRUPTIBLE_STATES
4. `TestStateMachineConcurrency` — Concurrent transitions are serialized by the lock
5. `TestStateMachineErrorRecovery` — Error counting, triple-failure guard, reset
6. `TestStateMachineStateDuration` — `state_duration_ms` accuracy
7. `TestStateMachineCallbacks` — Enter/exit callbacks fire at correct times

### File: `tests/services/orchestrator/core/test_pipeline.py` (NEW) — Pipeline Unit Tests

**Test classes (using mocked clients):**
1. `TestRealtimePipelineStates` — FSM state sequence follows expected path
2. `TestRealtimePipelinePushAudio` — Audio accepted only in AUDIO_INPUT_STATES
3. `TestRealtimePipelineSpeechEnd` — speech_end triggers concurrent pipeline
4. `TestRealtimePipelineBargeIn` — Barge-in stops TTS, transitions to LISTENING
5. `TestRealtimePipelineCancel` — Cancel clears state, resets FSM
6. `TestRealtimePipelineError` — STT/LLM/TTS failures transition to ERROR
7. `TestRealtimePipelineSentenceChunking` — Multi-sentence LLM output is chunked and each sentence triggers TTS call

### File: `tests/test_ws_security.py` (AMEND)

**Changes needed:**
1. Line 11: `PipelineError` import stays (it's still in pipeline.py)
2. `TestAudioBufferOverflow` class: Update to use `RealtimePipeline` instead of `StreamingPipeline`. The buffer test should verify `push_audio()` behavior instead.
3. `TestPipelineBusyReset` class: Rewrite tests to work with FSM states instead of `pipeline_busy` boolean. Test that after an error, the FSM is in ERROR state and subsequent cancel resets to IDLE.
4. `TestStopHandler` class: Verify that stop triggers FSM transition and resets VAD.

**Key change pattern for tests:**
```python
# Before:
pipeline = StreamingPipeline(...)
pipeline.add_audio(data)
pipeline_busy = True

# After:
pipeline = RealtimePipeline(...)
pipeline.push_audio(data)
assert pipeline.fsm.state == FSMState.LISTENING
```

### Running Tests

```bash
# FSM unit tests (fast, no external deps)
pytest tests/test_fsm.py -v

# Pipeline unit tests (mocked clients)
pytest tests/services/orchestrator/core/test_pipeline.py -v

# WS handler tests (mocked clients + TestClient)
pytest tests/test_ws_security.py -v

# TTS chunker tests
pytest tests/services/tts/test_chunker.py -v

# Full suite (expect ~240+ tests after Phase 3)
pytest -v
```

---

## Risks & Mitigations

### Risk 1: Pipeline rewrite breaks existing WS tests
**Severity:** High
**Mitigation:** Keep all exception classes and dataclasses in `pipeline.py` with same names. Update `test_ws_security.py` in Batch 5 to use the new API. The `test_streaming.py` tests will need updating too — defer this to a later session or include in Batch 5 if time permits.

### Risk 2: Sentence boundary detection produces bad splits
**Severity:** Medium
**Mitigation:** The `SENTENCE_BOUNDARY` regex handles 90%+ of cases. Abbreviations are handled with a heuristic (lowercase check after period). Edge cases improve over time. The `max_chars` safety valve prevents unbounded buffering.

### Risk 3: Barge-in causes audio artifacts (pop/click)
**Severity:** Medium
**Mitigation:** The jitter mechanism finishes the current 200ms chunk, preventing mid-sample truncation. Frame alignment (`frame_size` rounding) ensures we stop at a valid sample boundary. The `barge_in_jitter_ms` config allows tuning.

### Risk 4: FSM lock contention under high concurrency
**Severity:** Low
**Mitigation:** The `asyncio.Lock` is per-instance, so each WebSocket connection has its own FSM. The lock only guards brief state transitions, not long-running operations.

### Risk 5: Cross-service import from TTS chunker
**Severity:** Medium
**Mitigation:** The orchestrator imports `SentenceChunker` from `tts.chunker`. This creates a dependency from orchestrator→tts service. For now this is fine (both are Python packages in the same monorepo). Long-term, the chunker should move to `shared` or the orchestrator should use TTS service's streaming endpoint directly.

---

## Execution Order for Parallel Agents

Given 6 batches, here's the optimal parallel execution plan:

```
Step 1: Batch 0a, 0b, 0c, 0d (all parallel — 4 agents)
Step 2: Batch 1 (depends on 0a), Batch 2 (depends on 0b) — parallel
Step 3: Batch 3 (depends on 1, 2) — single agent
Step 4: Batch 4 (depends on 3) — single agent
Step 5: Batch 5 (depends on 3, partially on 4) — single agent

Total wall clock: ~5 sequential steps, ~12-15h with multiple agents
```

### Agent Assignment

| Agent | Batch | Skills Needed |
|-------|-------|--------------|
| Agent 1 | 0a (state.py) + 1 (state_machine.py) | Python patterns, async patterns |
| Agent 2 | 0b (chunker.py partial) + 2 (chunker.py full) | Python, regex, async generators |
| Agent 3 | 0c (config.py) + 0d (settings.yaml) | Pydantic, YAML config |
| Agent 4 | 3 (pipeline.py rewrite) | **Expert**: asyncio TaskGroup, async generators, FSM, streaming |
| Agent 5 | 4 (ws.py rewrite + main.py) | **Expert**: FastAPI WebSocket, state machines, async |
| Agent 6 | 5 (tests) | pytest, mocking, async testing |

---

## Success Criteria

- [ ] `FSMState` enum in `shared/src/shared/state.py` with all 7 states and transition table
- [ ] `StateMachine` class with lock-safe transitions, enter/exit callbacks, error counting
- [ ] `SentenceChunker` correctly splits streaming text into sentences
- [ ] `RealtimePipeline` runs STT, LLM, and TTS as concurrent tasks
- [ ] Barge-in stops TTS within 200ms jitter window and transitions to LISTENING
- [ ] WS handler dispatches events based on FSM state (not boolean flag)
- [ ] Listening timeout triggers after configurable seconds in LISTENING state
- [ ] ERROR state with triple-failure guard stops auto-recovery
- [ ] All existing tests still pass (updated for new API)
- [ ] FSM unit tests cover valid/invalid transitions, concurrency, error recovery
- [ ] `ruff check .` passes
