# J.A.R.V.I.S. — Implementation Schedule

> Generated from blueprint at `jarvis_blueprint.md` (485 lines).  
> This schedule is a living document — update estimates as real data arrives from each phase.

---

## Phase Dependency Graph

```
                         ┌──────────┐
                         │  Phase 0  │  Skeleton (Git, Docker, config, shared/)
                         └─────┬─────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
         ┌──────▼──────┐     │       ┌───────▼────────┐
         │ Phase 0.5    │     │       │   Phase 1      │
         │ Audio I/O    │     │       │   Text Brain    │
         └──────┬───────┘     │       └───────┬────────┘
                │              │              │
                └──────┬───────┘              │
                       │                      │
                       └──────────┬───────────┘
                                  │
                          ┌───────▼────────┐
                          │   Phase 2      │
                          │  Voice I/O      │
                          │  (turn-based)   │
                          └───────┬────────┘
                                  │
                          ┌───────▼────────┐
                          │  Phase 2.5     │
                          │  Streaming (no │
                          │   barge-in)    │
                          └───────┬────────┘
                                  │
                          ┌───────▼────────┐
                          │   Phase 3      │◄────── Critical Path Core
                          │  Real-time      │
                          │  Streaming      │
                          └───────┬────────┘
                                  │
                  ┌───────────────┼────────────────┐
                  │               │                 │
          ┌───────▼──────┐ ┌──────▼───────┐        │
          │  Phase 4      │ │  Phase 5     │        │
          │  Memory       │ │  Tool Calling│        │
          └───────┬───────┘ └──────┬───────┘        │
                  │                │                 │
                  └───────┬────────┘                 │
                          │                          │
                   ┌──────▼───────┐                  │
                   │  Phase 6     │◄─────────────────┘
                   │  Agentic +   │  (also needs Phase 5)
                   │  Robotics    │
                   └──────┬───────┘
                          │
                   ┌──────▼───────┐
                   │  Phase 7     │
                   │  Deployment  │
                   └──────────────┘
```

### Dependency Table

| Phase | Depends On | Reason |
|-------|-----------|--------|
| 0 | Nothing | Foundation for everything |
| 0.5 | Phase 0 | Shares `shared/` package, config, logging |
| 1 | Phase 0 | Shares `shared/` package, config, logging |
| 2 | Phase 0.5, Phase 1 | Audio I/O needed for mic/speaker; Phase 1 LLM for brain |
| 2.5 | Phase 2 | Streaming builds on turn-based voice pipeline |
| 3 | Phase 2.5 | Real-time streaming cannot be built on unstable base |
| 4 | Phase 3 | Memory injection into streaming pipeline requires stable orchestrator |
| 5 | Phase 3 | Tool calls integrate with orchestrator FSM (TOOL_WAITING state) |
| 6 | Phase 5 (tools), Phase 4 (memory) | ReAct loop chains tool calls; memory enriches planning |
| 7 | Phase 3 minimum; ideal after Phase 6 | 24/7 daemon only useful after core is stable; observability covers all services |

---

## Phase-by-Phase Breakdown

---

### Phase 0 — Skeleton

**Goal:** Repo and infra skeleton — Git, Docker, config system, logging, health checks, graceful shutdown, rate limiting, CI.

**Dependencies:** None  
**Estimated effort:** 35–45 hours  
**Risk level:** Low  
**Blueprint reference:** §1 (Phase 0 row), §5 (Phase 0 — Skeleton section), §5 (monorepo structure diagram), §7 (CI/CD), §8 (security basics)
→ **Test spec:** [§3 in tests.md](./tests.md#3-phase-0--skeleton)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 0.1 | Initialize monorepo with directory structure | `(project root)` | 1 | Create all directories per §5 monorepo tree: `config/prompts/tools/`, `shared/src/shared/`, `services/{orchestrator,stt,tts,memory,tools}/`, `scripts/`, `tests/`, `.github/workflows/` |
| 0.2 | Create `.gitignore` | `.gitignore` | 0.5 | Ignore `__pycache__`, `.env`, `*.egg-info`, `.pytest_cache`, `dist/`, `*.whl`, Docker volumes, model weights |
| 0.3 | Create `.dockerignore` | `.dockerignore` | 0.5 | Ignore `__pycache__`, `.git`, `.env`, `tests/`, `*.md` in Docker context |
| 0.4 | Create `.env.example` | `.env.example` | 0.5 | Template with all env vars: `REDIS_URL`, `OLLAMA_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `LOG_LEVEL`, `REDIS_PASSWORD`, etc. |
| 0.5 | Create `config/settings.yaml` | `config/settings.yaml` | 2 | Central configuration file: model choices (LLM provider, model name), rate limits per endpoint, audio params (sample rate, channels), logging level, service ports, Redis config, wake word settings, listening timeout |
| 0.6 | Create `config/settings.schema.json` | `config/settings.schema.json` | 2 | JSON Schema for `settings.yaml` validation at startup |
| 0.7 | Create `shared/src/shared/config.py` | `shared/src/shared/config.py` | 3 | Pydantic Settings v2 with nested models for LLM, STT, TTS, Redis, audio, tools, rate limits, logging. Validate at import time — fail fast on missing required keys. |
| 0.8 | Create `shared/src/shared/messages.py` | `shared/src/shared/messages.py` | 4 | Pydantic models for **all 16 message types** (§2.1): `TRANSCRIPT_PARTIAL`, `TRANSCRIPT_FINAL`, `VAD_SPEECH_START`, `VAD_SPEECH_END`, `TTS_SYNTHESIZE`, `TTS_STOP`, `TTS_AUDIO_CHUNK`, `TTS_COMPLETE`, `LLM_GENERATE`, `LLM_CANCEL`, `LLM_TOKEN`, `LLM_COMPLETE`, `LLM_TOOL_CALL`, `MEMORY_STORE`, `MEMORY_RETRIEVE`, `MEMORY_RETRIEVE_RESULT`. Envelope: `type`, `payload`, `request_id`, `timestamp`. Discriminated union via Pydantic discriminated union. |
| 0.9 | Create `shared/src/shared/state.py` | `shared/src/shared/state.py` | 2 | Enums for orchestrator states (§3, Phase 3): `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `INTERRUPTED`, `TOOL_WAITING`, `ERROR`. Reusable by orchestrator, clients, and tests. |
| 0.10 | Create `shared/src/shared/logging.py` | `shared/src/shared/logging.py` | 3 | structlog configuration: JSON formatter, request_id propagation via context vars, timestamp in ISO 8601, configurable level from settings. |
| 0.11 | Create `shared/pyproject.toml` | `shared/pyproject.toml` | 1 | Package config: name `jarvis-shared`, Python 3.12+, deps: `pydantic>=2.0`, `structlog`, `pyyaml`. Editable install for local dev. |
| 0.12 | Create orchestrator skeleton | `services/orchestrator/src/orchestrator/main.py` | 3 | FastAPI app with: `GET /health` returning `{"status": "ok", "dependencies": {"redis": false}}`, rate limiting middleware (slowapi or custom), graceful shutdown handler (SIGTERM → complete in-flight → ack messages → close connections → exit). |
| 0.13 | Create STT service skeleton | `services/stt/src/stt/main.py` | 1.5 | FastAPI app with `GET /health`, graceful shutdown. Placeholder routes. |
| 0.14 | Create TTS service skeleton | `services/tts/src/tts/main.py` | 1.5 | FastAPI app with `GET /health`, graceful shutdown. Placeholder routes. |
| 0.15 | Create memory service skeleton | `services/memory/src/memory/main.py` | 1.5 | FastAPI app with `GET /health`, graceful shutdown. Placeholder routes. |
| 0.16 | Create tools service skeleton | `services/tools/src/tools/main.py` | 1.5 | FastAPI app with `GET /health`, graceful shutdown. Placeholder routes. |
| 0.17 | Create `docker-compose.yml` | `docker-compose.yml` | 4 | Define services: orchestrator, stt, tts, memory, tools, redis, ollama (commented: "uncomment when needed"). Health checks on every service. Networks: `jarvis-net`. Volumes for Redis data, Ollama models. Port mappings. |
| 0.18 | Create `docker-compose.override.yml` | `docker-compose.override.yml` | 1 | Dev overrides: port forwarding, volume mounts for live code reload, `--reload` flag on uvicorn, env file loading. |
| 0.19 | Create Dockerfiles for each service | `services/*/Dockerfile` (5 files) | 3 | Multi-stage: builder stage (install deps, compile), runtime stage (slim Python 3.12 image, non-root user, copy dist only). |
| 0.20 | Create CI workflow | `.github/workflows/ci.yml` | 3 | Ruff lint, black format check, mypy type check, pytest unit tests, Docker build (all services). No model dependencies in CI. |
| 0.21 | Create dev/lint/test scripts | `scripts/dev.sh`, `scripts/lint.sh`, `scripts/test.sh` | 1.5 | Shell scripts wrapping docker-compose, ruff, mypy, pytest. |
| 0.22 | Create `tests/conftest.py` | `tests/conftest.py` | 2 | Shared pytest fixtures: mock Redis (fakeredis), test settings override, structlog capture, health check client. |
| 0.23 | Create health check integration tests | `tests/test_health.py` | 1 | For each service: start with mocked deps, verify `GET /health` returns 200 with expected dependency status. |

#### Parallelization Opportunities

- **Group A** (infrastructure): 0.1, 0.2, 0.3, 0.4 — can all be done in parallel, no dependencies
- **Group B** (config): 0.5, 0.6, 0.7 — sequential, each builds on prior
- **Group C** (shared package): 0.8, 0.9, 0.10, 0.11 — can be parallel after Group B
- **Group D** (service skeletons): 0.12, 0.13, 0.14, 0.15, 0.16 — fully parallelizable after Group C
- **Group E** (docker/ci): 0.17, 0.18, 0.19, 0.20 — can be parallel after Group D

#### Risks

- **Risk**: Over-engineering the shared package before understanding real usage patterns.  
  *Mitigation*: Keep message models minimal (only fields proven necessary). Extend later.
- **Risk**: Docker compose networking complexity slows down local dev.  
  *Mitigation*: Use `docker-compose.override.yml` for dev-friendly port mappings; add a `Makefile` with common commands from day one.
- **Risk**: Pydantic Settings validation too strict or too loose.  
  *Mitigation*: Define only required-for-startup keys as required; optional keys get sensible defaults.

#### Done Criteria

- [ ] `docker compose up` boots all 5 service containers + Redis, all report healthy via `docker compose ps`
- [ ] Every service's `GET /health` returns valid JSON with dependency status
- [ ] `shared` package installable via `pip install -e shared/` and importable by any service
- [ ] All Pydantic message types serialize/deserialize correctly with round-trip tests
- [ ] Rate limiting middleware returns 429 when limit exceeded (configurable threshold in `settings.yaml`)
- [ ] `SIGTERM` to any service: graceful shutdown completes within 10 seconds, log shows "shutdown complete"
- [ ] CI pipeline passes: ruff, black, mypy, pytest (all green)
- [ ] `settings.yaml` validates against `settings.schema.json`; missing required key causes loud startup failure with descriptive message
- [ ] structlog emits JSON-formatted logs with `request_id`, `timestamp`, `level`, `service` fields
- [ ] Monorepo directory structure matches §5 diagram exactly

---

### Phase 0.5 — Audio Primitives

**Goal:** AudioSource/AudioSink abstractions, WAV test fixtures, mockable I/O. Audio works in isolation before any STT/TTS service exists.

**Dependencies:** Phase 0 (shared/ package, config, logging)  
**Estimated effort:** 16–22 hours  
**Risk level:** Low  
**Blueprint reference:** §5 (Phase 0.5), §7.1 (Audio Testing Strategy)
→ **Test spec:** [§4 in tests.md](./tests.md#4-phase-05--audio-primitives)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 0.5.1 | Create `shared/src/shared/audio.py` — base abstractions | `shared/src/shared/audio.py` | 4 | `AudioSource` ABC: `open()`, `read(chunk_size) -> bytes`, `close()`. `AudioSink` ABC: `open()`, `write(chunk: bytes)`, `close()`. Context manager support. Audio format dataclass: `sample_rate`, `channels`, `sample_width`, `dtype`. |
| 0.5.2 | Implement `MicrophoneAudioSource` | `shared/src/shared/audio.py` | 2 | Uses `sounddevice.InputStream` to capture from default or named device. Configurable chunk size, sample rate, device index from settings. |
| 0.5.3 | Implement `SpeakerAudioSink` | `shared/src/shared/audio.py` | 2 | Uses `sounddevice.OutputStream` for playback. Non-blocking write. Configurable device, latency, buffer size. |
| 0.5.4 | Implement `FileAudioSource` | `shared/src/shared/audio.py` | 1.5 | Reads WAV file via `wave` or `scipy.io.wavfile`. Returns audio bytes chunk by chunk. Supports WAV at 16kHz and 44.1kHz mono. |
| 0.5.5 | Implement `NullAudioSink` | `shared/src/shared/audio.py` | 1 | Discards all written bytes. Counts total bytes written (for throughput/latency benchmarks). Optionally measures time gap between writes. |
| 0.5.6 | Create WAV test fixtures | `tests/fixtures/clean_speech_16k.wav`, `tests/fixtures/noisy_speech_16k.wav`, `tests/fixtures/silence_16k.wav`, `tests/fixtures/short_utterance_16k.wav`, `tests/fixtures/clean_speech_44k.wav` | 2 | Generate (or commit binary) 5 short WAV files per §7.1 spec: clean speech 16kHz mono, speech with noise, silence (3s), short utterance (<1s), clean speech 44.1kHz. Each <10s. Include known transcriptions in a JSON sidecar. |
| 0.5.7 | Create audio abstraction unit tests | `tests/test_audio.py` | 3 | Test `FileAudioSource` reads all expected bytes, `NullAudioSink` discards and counts, `SpeakerAudioSink` accepts valid audio, `MicrophoneAudioSource` produces bytes. Mark hardware tests with `@pytest.mark.audio_hardware`. |
| 0.5.8 | Create audio format validation | `shared/src/shared/audio.py` | 1.5 | Validate WAV headers: matching sample rate, expected channels. Reject incompatible formats with clear error messages before any audio processing. |
| 0.5.9 | Create audio pipeline integration test | `tests/test_audio_pipeline.py` | 2 | Wire `FileAudioSource` → processing (passthrough) → `NullAudioSink`. Verify bytes in ≈ bytes out (within chunk alignment). Measure throughput. |

#### Parallelization Opportunities

- **Tasks 0.5.1** (base abstractions) must come first
- **Tasks 0.5.2 & 0.5.3** (mic + speaker) can be done in parallel after 0.5.1
- **Tasks 0.5.4 & 0.5.5** (file source + null sink) can be done in parallel after 0.5.1
- **Tasks 0.5.6 & 0.5.7** can start as soon as 0.5.1 and 0.5.4 are done
- **Task 0.5.9** must wait for 0.5.4, 0.5.5, 0.5.6, 0.5.7

#### Risks

- **Risk**: `sounddevice` PortAudio dependency fails on some Linux setups.  
  *Mitigation*: Add `portaudio19-dev` to Dockerfile system deps; document host installation (`apt install portaudio19-dev python3-pyaudio`); CI tests use `FileAudioSource` + `NullAudioSink` exclusively (no hardware dep).
- **Risk**: WAV fixtures with speech content may have licensing issues if generated from copyrighted sources.  
  *Mitigation*: Generate synthetic test audio using `numpy` + `scipy` (sine waves, noise, silence) or use public-domain speech samples.
- **Risk**: Threading issues in `MicrophoneAudioSource` callbacks.  
  *Mitigation*: Use `sounddevice`'s blocking `read()` in a background thread with a queue; test with `FileAudioSource` for determinism.

#### Done Criteria

- [ ] `pytest tests/test_audio.py` passes (with `--audio` flag for hardware tests)
- [ ] `FileAudioSource` reads all 5 WAV fixtures to completion, emitting correct byte counts
- [ ] `NullAudioSink` discards all bytes and reports accurate byte counts
- [ ] `MicrophoneAudioSource` captures at least 1 second of audio when run with `--audio`
- [ ] `SpeakerAudioSink` plays a WAV file without distortion when run with `--audio`
- [ ] Audio format validation rejects mismatched sample rates with descriptive error
- [ ] FileAudioSource → NullAudioSink pipeline test: bytes in equals bytes out (within chunk alignment)
- [ ] Test fixtures are reproducible (deterministic generation script)

---

### Phase 1 — Text Brain

**Goal:** LLM client via Ollama, system prompt v1, CLI streaming chat loop. Type a question, get a coherent streamed answer.

**Dependencies:** Phase 0 (shared/ package, config, logging, health checks)  
**Estimated effort:** 22–28 hours  
**Risk level:** Low-Medium  
**Blueprint reference:** §1 (Phase 1), §5 (Phase 1), §6 (System prompt skeleton), §8
→ **Test spec:** [§5 in tests.md](./tests.md#5-phase-1--text-brain)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 1.1 | Create LLM client abstraction | `services/orchestrator/src/orchestrator/clients/llm.py` | 4 | Async client class: `generate(messages: list, stream: bool) -> AsyncIterator[str]`. Supports Ollama (via `httpx` to local API). Abstract base for future cloud providers. Configurable model name, temperature, max tokens from settings. |
| 1.2 | Implement Ollama client | `services/orchestrator/src/orchestrator/clients/llm.py` | 3 | Call Ollama `/api/chat` with streaming. Parse NDJSON stream, yield tokens. Handle errors: connection refused, model not found, timeout. Auto-retry on transient failures (up to 2 retries). |
| 1.3 | Create system prompt v1 | `config/prompts/v1_system.md` | 2 | Per §6 skeleton: voice-first, concise (1-3 sentence default), no markdown in voice responses, tool-use when appropriate, confirmation for irreversible actions. `{retrieved_memory}` and `{short_term_buffer}` placeholder slots. |
| 1.4 | Create prompt loader | `services/orchestrator/src/orchestrator/core/prompt.py` | 2 | Load prompt templates from files, render with context variables. Cache loaded prompts. Include version metadata in every response. Support `{retrieved_memory}` and `{short_term_buffer}` injection. |
| 1.5 | Create `/chat` streaming endpoint | `services/orchestrator/src/orchestrator/routes/chat.py` | 4 | FastAPI `POST /chat` with SSE streaming (`text/event-stream`). Accept `{messages: list, stream: bool}`. Stream tokens as `data: {"token": "Hello", "done": false}\n\n`. Handle cancellation (client disconnect stops LLM generation). |
| 1.6 | Create CLI client | `services/orchestrator/cli_chat.py` (or `scripts/chat.py`) | 3 | `python cli_chat.py` opens an interactive prompt. `stdin` → HTTP POST to `/chat` → streamed `stdout`. Readline support with `aioconsole`. Exit with `/exit` or Ctrl+C. Print full conversation on exit. |
| 1.7 | Create prompt version tracking | `shared/src/shared/messages.py` (extend) + `services/orchestrator/src/orchestrator/core/prompt.py` | 2 | Add `prompt_version` field to LLM generation metadata. Log prompt version with every response for A/B comparison. |
| 1.8 | Create Ollama Docker service | `docker-compose.yml` (extend) | 1 | Add `ollama` service: `ollama/ollama` image, model volume mount, `restart: unless-stopped`, port 11434, health check via `ollama list`. |
| 1.9 | Create text brain integration tests | `tests/test_chat.py` | 3 | Mock Ollama HTTP responses. Test: streaming tokens arrive correctly, error handling (model not found, timeout, invalid request), cancellation via client disconnect, prompt version logged. |
| 1.10 | Add response length discipline | `config/prompts/v1_system.md` + `services/orchestrator/src/orchestrator/core/prompt.py` | 1 | Enforce max tokens (configurable, default 512). System prompt instructs concise responses. Add `max_tokens` override in chat request. |

#### Parallelization Opportunities

- **1.1 & 1.3** can start in parallel (LLM client abstraction + system prompt authoring are independent)
- **1.2** depends on 1.1; **1.4** depends on 1.3
- **1.5** depends on 1.2, 1.4
- **1.6** depends on 1.5
- **1.8** (Ollama Docker) can be done independently anytime
- **1.7** depends on 1.4

#### Risks

- **Risk**: Ollama not available on the target system or wrong version.  
  *Mitigation*: Containerize Ollama; pin version in `docker-compose.yml`; add clear startup error messages; document manual install as fallback.
- **Risk**: LLM response quality is poor (hallucination, bad tone, overly verbose).  
  *Mitigation*: Iterate on system prompt v1 starting with §6 skeleton; add few-shot examples; test with 10-20 representative prompts before moving on.
- **Risk**: Streaming SSE connections drop or stall.  
  *Mitigation*: Add keepalive pings every 15s on the SSE stream; handle client disconnect cleanly (cancel generation); timeout after 60s of no tokens.

#### Done Criteria

- [ ] `POST /chat` with `stream: true` returns SSE stream of tokens
- [ ] CLI client sends message via stdin, prints streaming response token-by-token
- [ ] Ollama model (Qwen2.5-8B or Llama 3.1-8B) loads and generates coherent responses
- [ ] System prompt correctly enforces concise responses (1-3 sentences for simple questions)
- [ ] No markdown formatting in responses when in "voice mode"
- [ ] Client disconnect cancels in-flight LLM generation (verified via test)
- [ ] Error handling: connection refused → clear error, model not found → descriptive message
- [ ] Prompt version is logged with every response
- [ ] `docker compose up` starts both orchestrator and Ollama; `/chat` works end-to-end
- [ ] All integration tests pass with mocked Ollama

---

### Phase 2 — Voice I/O (Turn-Based)

**Goal:** Record on keypress → faster-whisper transcribes → Phase 1 LLM pipeline → Piper/Kokoro synthesizes → play audio. Turn-based, not real-time.

**Dependencies:** Phase 0.5 (audio abstractions), Phase 1 (LLM chat pipeline)  
**Estimated effort:** 36–46 hours  
**Risk level:** Medium  
**Blueprint reference:** §1 (Phase 2), §5 (Phase 2), §4 (STT: faster-whisper, TTS: Piper/Kokoro), §8 (WebSocket auth)
→ **Test spec:** [§6 in tests.md](./tests.md#6-phase-2--voice-io-turn-based)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 2.1 | Create STT service — base + Whisper | `services/stt/src/stt/main.py`, `services/stt/src/stt/whisper_stt.py` | 6 | FastAPI service with `POST /transcribe` (accepts WAV bytes, returns JSON `{text, segments[], language}`). Loads `faster-whisper` `small` or `medium` model at startup. Async wrapper via `run_in_executor`. Configurable model size, device (cpu/cuda), compute type. |
| 2.2 | Create STT service — Docker + health | `services/stt/Dockerfile`, `services/stt/pyproject.toml` | 2 | Multi-stage Docker with CUDA support (optional). Model weights downloaded at container start, cached in volume. |
| 2.3 | Create TTS service — base + Piper | `services/tts/src/tts/main.py`, `services/tts/src/tts/piper_tts.py` | 5 | FastAPI service with `POST /synthesize` (accepts text, returns WAV bytes). Loads Piper model at startup. Configurable voice, speed, model path. Async via `run_in_executor`. |
| 2.4 | Create TTS service — Kokoro alternative | `services/tts/src/tts/kokoro_tts.py` | 3 | Optional TTS backend. Same API surface as Piper. Switchable via `settings.yaml` under `tts.provider`. |
| 2.5 | Create TTS service — Docker + health | `services/tts/Dockerfile`, `services/tts/pyproject.toml` | 2 | Multi-stage Docker. Voice model files cached in Docker volume. |
| 2.6 | Create turn-based voice command client | `services/orchestrator/cli_voice.py` | 5 | Python script: keypress to start recording (e.g., spacebar), MicrophoneAudioSource captures until Enter, sends to STT `/transcribe`, sends text to Phase 1 `/chat`, sends response text to TTS `/synthesize`, plays result via SpeakerAudioSink. Reports timing for each stage. |
| 2.7 | Create voice pipeline orchestrator endpoint | `services/orchestrator/src/orchestrator/routes/voice.py` | 5 | `POST /voice` — accepts audio bytes → calls STT → calls LLM → calls TTS → returns audio bytes. Synchronous wrapper for the turn-based case. Orchestration logic that could later be replaced by the FSM. |
| 2.8 | Add WebSocket authentication | `services/orchestrator/src/orchestrator/routes/ws.py` | 3 | API key validation at WebSocket upgrade time. Reject with 401 if missing/invalid. Key loaded from settings/environment. |
| 2.9 | Add TTS audio format tests | `tests/test_tts.py` | 2 | Mock Piper response. Verify WAV output has correct format (sample rate, channels, bit depth). Test error handling for empty/very long text. |
| 2.10 | Add STT transcription tests | `tests/test_stt.py` | 2 | Test with WAV fixtures from Phase 0.5. Verify transcription returns expected text, segments, language. Test with clean, noisy, and silent audio. |
| 2.11 | Create end-to-end turn-based test | `tests/test_voice_turn.py` | 3 | Wire `FileAudioSource` (clean speech fixture) → STT → LLM (mocked) → TTS (mocked) → `NullAudioSink`. Verify the round trip produces expected text output and audio bytes. Measure round-trip time. |
| 2.12 | Add session token to message protocol | `shared/src/shared/messages.py` (extend) | 1 | Add optional `session_id` and `user_id` fields to message envelope. Used for auth and memory scoping from Phase 2 onward. |
| 2.13 | Benchmark and tune round-trip latency | `scripts/bench_voice.py` | 2 | Measure each stage (STT, LLM, TTS) independently with WAV fixtures. Report p50/p95/p99 latency. Aim for <4s total turn-based round trip. |

#### Parallelization Opportunities

- **Group A** (STT): 2.1, 2.2 — sequential
- **Group B** (TTS): 2.3, 2.4, 2.5 — can be parallel with Group A
- **Group C** (wire-up): 2.6, 2.7 — after Group A + B + Phase 1.5
- **Group D** (auth + protocol): 2.8, 2.12 — can be parallel with Groups A and B
- **Group E** (tests): 2.9, 2.10, 2.11 — after Groups A and B
- **Group F** (benchmark): 2.13 — after Phase 2 is otherwise done

#### Risks

- **Risk**: faster-whisper CPU inference is too slow for real-time feel (>2s for a 5s utterance).  
  *Mitigation*: Use `tiny` or `base` model on CPU initially; document GPU acceleration path; measure and report latency; Phase 2 is intentionally turn-based so sub-real-time is acceptable.
- **Risk**: Piper voice quality too synthetic.  
  *Mitigation*: Kokoro alternative ready in 2.4; document XTTS-v2 path for higher quality (trade-off: slower); voice quality is a Phase 2 concern — Phase 3+ can swap.
- **Risk**: Keypress recording UX is awkward and masks audio I/O issues.  
  *Mitigation*: This is intentional — the unnatural interaction forces clear debugging boundaries. Audio is tested in isolation in Phase 0.5; the turn-based phase catches integration bugs before streaming complexity.

#### Done Criteria

- [ ] `POST /transcribe` returns accurate transcription for all 5 WAV test fixtures (90%+ WER)
- [ ] `POST /synthesize` returns valid WAV audio for any text input
- [ ] `POST /voice` end-to-end: audio bytes in → audio bytes out, total <6s on target hardware
- [ ] Keypress recording client: spacebar records, Enter transcribes, audio plays back
- [ ] Piper and Kokoro both work (switchable via config)
- [ ] WebSocket connections without valid API key are rejected (401)
- [ ] Round-trip latency benchmark script reports per-stage timing
- [ ] End-to-end turn-based test passes with FileAudioSource and NullAudioSink
- [ ] `docker compose up` includes stt, tts, orchestrator, redis, ollama — all healthy

---

### Phase 2.5 — Streaming Without Barge-In

**Goal:** WebSocket streaming audio, streaming STT partials, streaming LLM, full-utterance TTS. User speaks without keypress, sees streaming text, waits for full audio response. No concurrent I/O or interruption.

**Dependencies:** Phase 2 (turn-based voice pipeline working)  
**Estimated effort:** 30–38 hours  
**Risk level:** Medium-High  
**Blueprint reference:** §1 (Phase 2.5), §5 (Phase 2.5), §5 (Phase 3 VAD mention)
→ **Test spec:** [§7 in tests.md](./tests.md#7-phase-25--streaming-without-barge-in)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 2.5.1 | Create WebSocket streaming audio endpoint | `services/orchestrator/src/orchestrator/routes/ws.py` | 5 | FastAPI WebSocket `/ws/audio`. Accepts binary audio frames (raw PCM). Sends JSON control messages (transcript partials, tokens, audio metadata). Per-frame acknowledgment for backpressure. |
| 2.5.2 | Create streaming WebSocket client | `services/orchestrator/cli_stream.py` | 3 | Python CLI: connects via WebSocket, streams audio from MicrophoneAudioSource, displays incoming transcript partials and LLM tokens, plays final audio via SpeakerAudioSink. |
| 2.5.3 | Add Silero VAD for endpointing (basic) | `services/stt/src/stt/vad.py` | 5 | Load Silero VAD model. `is_speech(chunk) -> bool`. Configurable threshold. Used to detect end-of-utterance (800ms silence). Emits `VAD_SPEECH_START`/`VAD_SPEECH_END` events. |
| 2.5.4 | Implement streaming STT with partials | `services/stt/src/stt/whisper_stt.py` (extend) | 5 | Accept streaming audio chunks. Run Whisper on rolling windows. Emit `TRANSCRIPT_PARTIAL` as user speaks, `TRANSCRIPT_FINAL` on VAD endpoint. Use Silero VAD for endpointing vs. Whisper's own endpointing. |
| 2.5.5 | Forward LLM tokens as streaming text to client | `services/orchestrator/src/orchestrator/core/pipeline.py` | 3 | Orchestrator routes `TRANSCRIPT_FINAL` → `LLM_GENERATE` → forward `LLM_TOKEN` events to WebSocket client as SSE-formatted text. |
| 2.5.6 | Implement full-utterance TTS (wait for complete response) | `services/tts/src/tts/main.py` (extend) | 4 | TTS service accumulates complete LLM response text, then synthesizes entire utterance, streams `TTS_AUDIO_CHUNK` messages back. No sentence-chunking yet. |
| 2.5.7 | Create streaming pipeline coordinator | `services/orchestrator/src/orchestrator/core/pipeline.py` | 5 | Coordinates: WebSocket → audio chunks → STT service → LLM generation → TTS synthesis → WebSocket audio out. Sequential stages (no concurrent I/O). Stop recording → process → respond → start recording. |
| 2.5.8 | Handle client disconnection in streaming | `services/orchestrator/src/orchestrator/routes/ws.py` | 2 | On WebSocket disconnect: cancel in-flight STT, cancel LLM generation, stop TTS playback. Clean up streaming state per session. |
| 2.5.9 | Create streaming integration tests | `tests/test_streaming.py` | 4 | Mock all services. Test: audio → partial transcripts, final transcript → LLM tokens → TTS audio. Test disconnect mid-stream. Test VAD endpointing with silence fixture. Measure streaming throughput. |
| 2.5.10 | Add streaming latency benchmark | `scripts/bench_streaming.py` | 2 | Measure: time from end-of-speech to first STT partial, final transcript to first LLM token, first sentence to first TTS audio byte. Report p50/p95. |

#### Parallelization Opportunities

- **2.5.3** (VAD) can start as soon as Phase 2 STT is done
- **2.5.1 & 2.5.2** (WebSocket endpoint + client) can be parallel with 2.5.3
- **2.5.4** (streaming STT) depends on 2.5.3
- **2.5.5 & 2.5.6** can be parallel after basic streaming is defined
- **2.5.7** (pipeline coordinator) must come after most components exist
- **2.5.9 & 2.5.10** must come after 2.5.7

#### Risks

- **Risk**: WebSocket binary framing for audio is error-prone (packet boundaries, byte ordering).  
  *Mitigation*: Use a lightweight binary protocol: 4-byte length prefix + JSON header + audio payload. Document framing format. Add hex dump debug mode.
- **Risk**: Silero VAD false positives/negatives cause premature endpointing or missed end-of-speech.  
  *Mitigation*: Configurable threshold and silence duration (in `settings.yaml`). Test with all 5 WAV fixtures including noisy and silence samples.
- **Risk**: Streaming STT partials are not useful (Whisper produces garbled partials).  
  *Mitigation*: Test with clean speech first; partial quality is a UX bonus, not a requirement — `TRANSCRIPT_FINAL` is the ground truth.
- **Risk**: Sequential recording → respond → recording feels slow (no overlap).  
  *Mitigation*: This is intentional — Phase 2.5 exposes streaming bugs without concurrency complexity. Accept the UX limitation.

#### Done Criteria

- [ ] User speaks without pressing a key; streaming partial transcripts appear on screen
- [ ] `TRANSCRIPT_FINAL` fires within 1s of end-of-speech (on clean audio)
- [ ] LLM tokens stream to client as they arrive
- [ ] Full-utterance TTS playback plays after LLM completes
- [ ] Sequential I/O enforced: recording stops before LLM/TTS starts
- [ ] Client disconnect cancels all in-flight operations and cleans up
- [ ] VAD correctly detects end-of-speech for clean speech (tested with fixtures)
- [ ] Audio → STT → LLM → TTS pipeline test passes with mocked components
- [ ] End-to-end latency measured and baseline established (<6s total for streaming case)
- [ ] Streaming CLI client works: continuous mic capture, streaming text display, audio playback

---

### Phase 3 — Real-Time Streaming

**Goal:** Formal 7-state orchestrator FSM, VAD + wake word, sentence-chunked TTS, barge-in with 200ms jitter control. Feels like a conversation.

**Dependencies:** Phase 2.5 (streaming without barge-in working and stable)  
**Estimated effort:** 70–90 hours  
**Risk level:** **High** — this is the hardest engineering phase in the entire project  
**Blueprint reference:** §1 (Phase 3), §3 (orchestrator state machine), §5 (Phase 3), §5 (latency budget table), §6
→ **Test spec:** [§8 in tests.md](./tests.md#8-phase-3--real-time-streaming)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 3.1 | Implement orchestrator FSM | `services/orchestrator/src/orchestrator/core/state_machine.py` | 10 | Formal 7-state machine: `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `INTERRUPTED`, `TOOL_WAITING`, `ERROR`. Defined transitions per §3 diagram. Configurable LISTENING timeout (default 5s). Transition callbacks (enter/exit). Thread-safe state transitions via `asyncio.Lock`. State change events emitted on Redis stream. |
| 3.2 | Implement wake word detection | `services/orchestrator/src/orchestrator/core/wake_word.py` (or in orchestrator/clients/) | 5 | Integrate openWakeWord. `detect(audio_chunk) -> bool`. Configurable wake word(s) in settings. Runs continuously in IDLE state. Triggers LISTENING transition. |
| 3.3 | Implement sentence-chunked TTS | `services/tts/src/tts/main.py` (extend) + `services/tts/src/tts/chunker.py` | 6 | Accept streaming LLM text. Sentence-segment using heuristics (`.`, `!`, `?`, `\n\n`). Synthesize each sentence as it completes. Stream `TTS_AUDIO_CHUNK` per sentence. First-sentence latency target: <200ms. |
| 3.4 | Implement barge-in with jitter control | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 6 | When VAD detects user speech during SPEAKING state: finish current 200ms TTS chunk, then stop playback. Transition SPEAKING → INTERRUPTED → LISTENING. Cancel in-flight LLM. Clear pending TTS queue. |
| 3.5 | Implement concurrent I/O in pipeline | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 6 | Overlap STT capture with LLM generation with TTS playback. WebSocket audio in → STT streaming → LLM streaming → TTS chunked streaming → WebSocket audio out. All stages can be active simultaneously. |
| 3.6 | Implement cold-start warmup | `services/orchestrator/src/orchestrator/clients/llm.py` (extend) | 2 | On orchestrator boot: send a short dummy prompt to Ollama to load weights. Use `keep_alive: -1` to keep model resident. Also warm up VAD and TTS models. |
| 3.7 | Implement sliding-window prompt truncation | `services/orchestrator/src/orchestrator/core/prompt.py` (extend) | 3 | Track total tokens in conversation buffer. Before exceeding context window, drop oldest complete turns (question + answer pairs). Never truncate mid-response. |
| 3.8 | Add FSM visualization and logging | `services/orchestrator/src/orchestrator/core/state_machine.py` (extend) | 2 | Log every state transition with timing: `[FSM] IDLE -> LISTENING (5.23s since boot)`. Optional Mermaid state diagram export for debugging. |
| 3.9 | Add listening timeout with feedback | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 2 | Configurable timeout (default 5s). If no speech detected, transition IDLE → produce "I didn't catch that" spoken prompt. Distinguish from VAD silence threshold. |
| 3.10 | Implement VAD integration in streaming pipeline | `services/stt/src/stt/vad.py` (extend) + orchestrator pipeline | 4 | VAD runs on incoming audio stream, emits events. Orchestrator consumes events for: start-of-speech (trigger PROCESSING? No — only after VAD_END), end-of-speech (trigger PROCESSING), barge-in detection during SPEAKING. |
| 3.11 | Implement TOOL_WAITING UI feedback | `services/orchestrator/src/orchestrator/core/pipeline.py` | 1.5 | When state enters TOOL_WAITING, send signal to client: show "running a tool" indicator or play subtle thinking sound. |
| 3.12 | Implement ERROR state and recovery | `services/orchestrator/src/orchestrator/core/state_machine.py` (extend) | 3 | Any component failure triggers ERROR state. Log error details. After configurable timeout (10s), attempt recovery → IDLE. If recovery fails 3 times consecutively, stay in ERROR. |
| 3.13 | Create latency budget regression tests | `tests/test_latency.py` | 4 | Measure each stage against §3 latency budget: STT TTFT <150ms, LLM TTFT <300ms, LLM TBT ~30-50ms/token, TTS TTFT <200ms, total voice-to-voice <1.5s. Run in CI with mocked components for consistency. |
| 3.14 | Create real-time streaming integration tests | `tests/test_realtime_stream.py` | 6 | Mock all services. Test every FSM transition. Test barge-in: inject VAD event during simulated SPEAKING state, verify transition. Test concurrent I/O: STT streaming while LLM generating while TTS playing. Test wake word → LISTENING → idle timeout. Test ERROR → recovery. |
| 3.15 | Barge-in jitter tuning experiment | `scripts/tune_barge_in.py` | 4 | Automated experiment: vary TTS chunk size (50ms, 100ms, 200ms, 400ms). Measure: perceived cut quality (human eval on recorded samples), interrupt latency (time from VAD to stop). Publish results in benchmark report. |
| 3.16 | Add state transition diagram to docs | `docs/state_machine.md` | 2 | Document all 7 states and transitions. Include Mermaid diagram. Reference for orchestrator maintainers. |
| 3.17 | Create warm-up sequence orchestrator startup | `services/orchestrator/src/orchestrator/main.py` (extend) | 2 | On startup: warm Ollama (dummy request), warm VAD (dummy audio), warm TTS (dummy text). Only accept requests after warm-up completes. |
| 3.18 | Implement Ollama keep_alive management | `services/orchestrator/src/orchestrator/clients/llm.py` (extend) | 1 | Set `keep_alive: -1` on model load to keep model resident in GPU memory. Log keep_alive status on health check. |
| 3.19 | Add per-session state isolation | `services/orchestrator/src/orchestrator/core/state_machine.py` (extend) | 3 | Each WebSocket connection gets its own FSM instance. Isolated state: one user's interrupt doesn't affect another. Clean up abandoned sessions via timeout. |
| 3.20 | Create real-time streaming CLI client | `services/orchestrator/cli_realtime.py` | 3 | Full CLI client: continuous mic capture, wake word activation, barge-in support, streaming text display, audio playback, thinking indicator for TOOL_WAITING. |

#### Parallelization Opportunities

- **3.1** (FSM) is foundational — most other tasks depend on it
- **3.2** (wake word) can be parallel with 3.1
- **3.3** (sentence-chunked TTS) can be parallel with 3.1 and 3.2
- **3.4** (barge-in) depends on 3.1 (FSM) and 3.3 (chunked TTS)
- **3.5** (concurrent I/O) depends on 3.1
- **3.6, 3.7, 3.8, 3.9** can be parallel after 3.1
- **3.10** (VAD integration) runs in parallel with 3.1
- **3.11, 3.12, 3.18, 3.19** — smaller tasks, can be parallel after 3.1
- **3.13, 3.14, 3.15** must come after everything else is stable
- **3.20** (CLI client) depends on most tasks being done

#### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Barge-in is unreliable** — too aggressive (cuts off assistant mid-word) or too lenient (doesn't interrupt when it should) | High — makes the assistant feel broken | Default to 200ms chunks; make chunk size configurable; dedicate 4h to tuning experiment (3.15); document that this is hard and imperfection is acceptable for v1 |
| **FSM race conditions** — two events firing simultaneously cause inconsistent state | High — could crash or produce infinite loops | `asyncio.Lock` on all state transitions; exhaustive state transition tests (3.14); log every transition with timestamp for post-mortem debugging |
| **Latency budget not met** — real HW can't achieve <1.5s voice-to-voice | Medium — assistant works but feels slow | Measure early (3.13); identify bottleneck by stage; document paid upgrade path (§10.1) if local HW is insufficient; accept 2-3s as "functional but not magical" |
| **Wake word false positives** — assistant activates on background conversation | Medium-high — frustrating UX | Configurable threshold; test in representative noise conditions; provide "push-to-talk" fallback mode |
| **Sentence chunker has bad heuristics** — splits in wrong places or misses sentence boundaries | Low-medium — audible but not broken | Use regex + ML fallback; make chunking configurable; iterate with real transcripts |

#### Done Criteria

- [ ] All 7 FSM states implemented with correct transitions per §3 diagram
- [ ] Wake word detected triggers IDLE → LISTENING transition
- [ ] VAD endpointing triggers LISTENING → PROCESSING transition
- [ ] Sentence-chunked TTS: first audio byte arrives <200ms after first sentence complete
- [ ] Barge-in: speaking during playback stops within 200ms, transitions to LISTENING
- [ ] Concurrent I/O: user can speak while assistant is speaking (barge-in), STT/LLM/TTS run simultaneously
- [ ] Listening timeout: 5s silence produces "I didn't catch that" spoken prompt
- [ ] Cold-start warmup: first request after boot has <2s latency (vs 5s+ without warmup)
- [ ] Sliding window: conversation > context window is truncated oldest-turn-first
- [ ] ERROR → IDLE recovery works after component failure
- [ ] TOOL_WAITING state signals "running a tool" to client
- [ ] Per-session isolation: two concurrent sessions don't interfere
- [ ] Latency budget tests pass: STT TTFT <150ms, LLM TTFT <300ms, LLM TBT <50ms, TTS TTFT <200ms (on reference HW with mocked components)
- [ ] All state transitions logged with timing, exportable as Mermaid diagram
- [ ] Real-time CLI client works: wake word → speak → hear response → interrupt → repeat
- [ ] Barge-in jitter report documents optimal chunk size for your HW

---

### Phase 4 — Memory

**Goal:** Short-term Redis buffer for recent conversation turns; long-term ChromaDB with fact extraction for permanent memory.

**Dependencies:** Phase 3 (stable orchestrator FSM to inject memory into)  
**Estimated effort:** 35–45 hours  
**Risk level:** Medium  
**Blueprint reference:** §1 (Phase 4), §5 (Phase 4), §4 (ChromaDB, Redis, nomic-embed-text), §6 (memory injection budget)
→ **Test spec:** [§9 in tests.md](./tests.md#9-phase-4--memory)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 4.1 | Create memory service skeleton + health | `services/memory/src/memory/main.py` | 2 | FastAPI service with Redis and ChromaDB health checks. Memory is a standalone service, not baked into orchestrator. |
| 4.2 | Create Redis connection manager | `services/memory/src/memory/short_term.py` | 3 | Async Redis client (redis-py async). `connect()` / `disconnect()`. Configurable URL, password from settings. Reconnection with exponential backoff. |
| 4.3 | Implement short-term buffer | `services/memory/src/memory/short_term.py` | 4 | Rolling window of last N turns (configurable, default 20). Stored as Redis list per session. `get_recent(session_id, limit) -> list[messages]`. `append(session_id, turn)`. Automatic eviction of oldest turns. |
| 4.4 | Create ChromaDB connection manager | `services/memory/src/memory/long_term.py` | 2 | ChromaDB client initialization. Configurable persistence path (default `./chroma_db`). Collection per user/session namespace. |
| 4.5 | Create embedding client | `services/memory/src/memory/long_term.py` | 3 | Use Ollama embedding models (`nomic-embed-text` or `bge-small`). `embed(text: str) -> list[float]`. Batch embed for efficiency. Cache results to avoid re-embedding identical text. |
| 4.6 | Implement fact extraction | `services/memory/src/memory/extraction.py` | 6 | After each turn, call small LLM (or same LLM with confined prompt) to extract facts: `{"facts": [{"subject": "user's dog", "predicate": "is named", "object": "Max", "category": "personal", "confidence": 0.95}]}`. Prompt: "Extract memorable facts from this conversation turn. Only extract if confidence > 0.7. Ignore greetings, small talk, and transient topics." |
| 4.7 | Implement long-term memory store | `services/memory/src/memory/long_term.py` (extend) | 4 | `store_facts(session_id, facts: list[dict])`: embed each fact and store in ChromaDB with metadata (timestamp, session_id, category, confidence). `search(query, top_k=5)`: embed query, semantic search, return top-k facts. |
| 4.8 | Implement memory retrieval for orchestrator | `services/orchestrator/src/orchestrator/clients/memory.py` | 3 | Orchestrator client for memory service. `get_relevant_memory(query: str, top_k=5) -> list[dict]`. Called before each LLM generation. Results injected into system prompt as `{retrieved_memory}`. |
| 4.9 | Integrate memory into system prompt | `config/prompts/v1_system.md` (modify) + `services/orchestrator/src/orchestrator/core/prompt.py` (extend) | 2 | Inject top-3 facts into system prompt slot. Format: `"Relevant past context:\n- User's dog is named Max\n- User works on robotics project"`. Capped at 3-5 facts per §6. |
| 4.10 | Create `MEMORY_STORE` / `MEMORY_RETRIEVE` message handlers | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 3 | Orchestrator emits `MEMORY_STORE` after each turn and `MEMORY_RETRIEVE` before each LLM generation. Memory service consumes and responds. |
| 4.11 | Add memory read/write policy (write filtering) | `services/memory/src/memory/extraction.py` (extend) | 2 | Skip storage for: short utterances (<5 words), greetings ("hello", "good morning"), trivial acknowledgments ("okay", "I see"). Configurable in settings. |
| 4.12 | Implement background fact extraction | `services/memory/src/memory/main.py` (extend) | 2 | Extraction happens in background after response is sent — never blocks the main pipeline. Queue-based with configurable rate. |
| 4.13 | Add memory expiry for short-term buffer | `services/memory/src/memory/short_term.py` (extend) | 1 | Redis TTL on conversation turns (configurable, default 24h). Short-term buffer auto-cleans. |
| 4.14 | Create memory integration tests | `tests/test_memory.py` | 4 | Test short-term: append, retrieve, eviction. Test long-term: store facts, semantic search returns relevant results, confidence filtering. Test extraction with known conversations. Test memory service health endpoint. |
| 4.15 | Add memory debugging CLI | `scripts/memory_debug.py` | 2 | CLI tool to inspect short-term buffer (by session), search long-term memory by query, list stored facts, purge memory. |

#### Parallelization Opportunities

- **4.1, 4.2, 4.3** (short-term) can be parallel with **4.4, 4.5, 4.6, 4.7** (long-term)
- **4.8, 4.9** (orchestrator integration) depends on both short-term and long-term being ready
- **4.10** (message handlers) depends on 4.8
- **4.11, 4.12** (policy + background) depend on 4.6
- **4.14, 4.15** depend on all core functionality

#### Risks

- **Risk**: Fact extraction LLM call adds latency or cost.  
  *Mitigation*: Run extraction in background after response (4.12). Use a smaller/cheaper model for extraction. Gate extraction on confidence threshold.
- **Risk**: ChromaDB query latency >100ms degrades the pipeline.  
  *Mitigation*: Monitor per §4 — if consistently above 100ms, migrate to PostgreSQL + pgvector. Start with small collections.
- **Risk**: Irrelevant memory injects noise into prompts, confusing the LLM.  
  *Mitigation*: Strict top-k cap (3-5 facts). Confidence threshold on extraction (0.7). Filter by category relevance. Test with adversarial queries.
- **Risk**: Redis data loss on restart.  
  *Mitigation*: Configure Redis AOF persistence; short-term buffer is ephemeral by design (long-term is source of truth).
- **Risk**: ChromaDB data corruption at scale.  
  *Mitigation*: Regular backup of ChromaDB persistence directory; document LUKS/fernet encryption per §8.

#### Done Criteria

- [ ] Short-term buffer stores last 20 turns per session; oldest evicted automatically
- [ ] Fact extraction: given a conversation turn, produces structured facts with confidence scores
- [ ] Trivial utterances (greetings, <5 words) are filtered from storage
- [ ] Long-term memory: store facts → semantic search retrieves relevant facts
- [ ] Memory injected into system prompt: `{retrieved_memory}` populated with 3-5 relevant facts
- [ ] Extraction runs in background (non-blocking to main pipeline)
- [ ] `MEMORY_STORE` / `MEMORY_RETRIEVE` messages flow over Redis Streams correctly
- [ ] Short-term buffer has TTL (configurable, default 24h)
- [ ] Memory debugging CLI can inspect and query memory
- [ ] All memory tests pass with mocked extraction LLM
- [ ] ChromaDB health reported in memory service health endpoint

---

### Phase 5 — Tool Calling

**Goal:** Tool registry, function calling, safety tiers (safe/confirm/restricted). Web search, file I/O, datetime as starter tools.

**Dependencies:** Phase 3 (orchestrator FSM with TOOL_WAITING state)  
**Estimated effort:** 30–40 hours  
**Risk level:** Medium  
**Blueprint reference:** §1 (Phase 5), §5 (Phase 5), §4 (Instructor, SearXNG, file analysis), §8 (tool safety tiers, sandboxing)
→ **Test spec:** [§10 in tests.md](./tests.md#10-phase-5--tool-calling)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 5.1 | Create tool registry | `services/tools/src/tools/registry.py` | 4 | Central registry: `register(tool: Tool)`, `get_tool(name) -> Tool`, `list_tools() -> list[Tool]`. `Tool` dataclass: `name`, `description`, `args_schema` (Pydantic model), `fn` (async callable), `safety_tier` (safe/confirm/restricted), `allowlist_required` bool. |
| 5.2 | Implement `get_datetime` tool | `services/tools/src/tools/registry.py` (inline) | 1 | Safe tier. Returns current date, time, timezone. No arguments. |
| 5.3 | Implement `web_search` tool | `services/tools/src/tools/web_search.py` | 5 | Use DuckDuckGo HTML search (no API key) or SearXNG self-hosted. `search(query: str, num_results: int = 5) -> list[dict]`. Return title, url, snippet. Safe tier. Configurable provider in settings. |
| 5.4 | Implement `read_file` tool | `services/tools/src/tools/file_io.py` | 4 | `read_file(path: str) -> str`. Path sandboxed to configured directory (reject `../../../etc/passwd`). Support `.txt`, `.md`, `.py`, `.json`, `.csv`. Return file contents. Safe tier. |
| 5.5 | Implement `get_weather` tool | `services/tools/src/tools/weather.py` | 3 | Use free weather API (wttr.in or Open-Meteo). `get_weather(location: str) -> str`. Safe tier. No API key required for Open-Meteo. |
| 5.6 | Create tool function-calling format converter | `services/tools/src/tools/registry.py` (extend) | 3 | Convert tool registry to OpenAI-compatible function-calling schema. `to_openai_schema(tools: list) -> list[dict]`. Used by LLM client to inject available tools. |
| 5.7 | Implement tool argument validation | `services/tools/src/tools/registry.py` (extend) | 2 | Validate all tool arguments against Pydantic schema before execution. Reject type mismatches and injection attempts with clear error. Never execute with invalid args. |
| 5.8 | Implement confirmation flow for "confirm" tier | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 4 | When tool is "confirm" tier: transition TOOL_WAITING → SPEAKING with "Shall I proceed?" prompt. Listen for user confirmation (yes/no). If yes, execute tool. If no, cancel. Document in system prompt. |
| 5.9 | Implement allowlist check for "restricted" tier | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 2 | Before executing restricted tool: check tool name against `settings.yaml` allowlist. If not in allowlist, reject with audible message. Log attempt. |
| 5.10 | Implement tool execution logging | `services/tools/src/tools/registry.py` (extend) | 1.5 | Log every tool invocation: timestamp, tool name, arguments, result (truncated), duration, session_id. Structured JSON via structlog. |
| 5.11 | Create tools service (FastAPI) | `services/tools/src/tools/main.py` | 3 | FastAPI service: `POST /tools/execute` (tool name + args → result), `GET /tools/list` (available tools with schemas). Docker + health. |
| 5.12 | Create orchestrator tool client | `services/orchestrator/src/orchestrator/clients/tools.py` | 2 | Async HTTP client for tools service. `execute(tool_name, args) -> Any`. Handles timeouts, retries (once), errors. |
| 5.13 | Extend LLM prompt with tool schemas | `services/orchestrator/src/orchestrator/core/prompt.py` (extend) | 2 | Inject available tools as OpenAI function schemas into LLM request. System prompt updated with tool instructions per §6. |
| 5.14 | Add `LLM_TOOL_CALL` handling in orchestrator | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 3 | When LLM emits `LLM_TOOL_CALL`: parse function call, route to tools service, inject result back into LLM context, continue generation. |
| 5.15 | Implement tool error handling | `services/orchestrator/src/orchestrator/core/pipeline.py` (extend) | 2 | Tool failure (timeout, invalid args, service down): emit audible "Sorry, I couldn't X because Y". Log error details. Transition to SPEAKING with error message. |
| 5.16 | Create tool calling integration tests | `tests/test_tools.py` | 4 | Mock LLM to emit tool calls. Test: tool execution, arg validation rejection, confirm tier pauses for confirmation, restricted tier blocked without allowlist, error handling. |

#### Parallelization Opportunities

- **5.1** (registry) is foundational
- **5.2, 5.3, 5.4, 5.5** (individual tools) can all be parallel after 5.1
- **5.6** (schema converter) depends on 5.1
- **5.7** (validation) depends on 5.1
- **5.8, 5.9** (pipeline integration) depend on 5.1 and Phase 3 FSM
- **5.11** (tools service) can be parallel with 5.2-5.5
- **5.12** depends on 5.11
- **5.13, 5.14, 5.15** depend on Phase 3 and basic tools

#### Risks

- **Risk**: LLM doesn't call tools correctly (calls wrong tool, invents tool names, malformed arguments).  
  *Mitigation*: Add few-shot examples in system prompt (§6). Validate arguments before execution (5.7). Log all attempts for debugging. Iterate on prompts.
- **Risk**: Web search returns unreliable or offensive content.  
  *Mitigation*: Filter results through content blocklist. Use SearXNG self-hosted for control. Never auto-execute write/action tools.
- **Risk**: File read tool exposes sensitive files despite sandboxing.  
  *Mitigation*: Path sandboxing with absolute path resolution + symlink checking. Restricted to configured directory by default. Log every file access.
- **Risk**: Instructor library doesn't support LLM's function-calling format.  
  *Mitigation*: Use raw OpenAI-compatible schemas with Ollama (Qwen2.5 supports it natively). Instructor is optional acceleration.

#### Done Criteria

- [ ] Tool registry: `register`, `get_tool`, `list_tools` work correctly
- [ ] `web_search` returns real search results from DuckDuckGo (or SearXNG)
- [ ] `read_file` reads files from sandboxed directory; rejects path traversal
- [ ] `get_datetime` returns current date/time/timezone
- [ ] `get_weather` returns weather for given location
- [ ] LLM correctly calls tools with valid arguments (tested with mocked LLM)
- [ ] "Confirm" tier tools: assistant says "Shall I proceed?", waits for user confirmation
- [ ] "Restricted" tier tools: blocked unless in allowlist
- [ ] Invalid tool arguments rejected with clear error before execution
- [ ] Tool failures produce audible error message and graceful recovery
- [ ] Every tool invocation logged: timestamp, tool, args, result, duration
- [ ] `POST /tools/execute` and `GET /tools/list` API endpoints working
- [ ] WebSocket connections include tool schemas in initial handshake message
- [ ] All tool tests pass with mocked LLM

---

### Phase 6 — Agentic + Robotics

**Goal:** ReAct-style plan → act → observe → replan loop. ROS2 bridge for robotics. Multi-step tool chaining.

**Dependencies:** Phase 5 (tool calling), Phase 4 (memory for history across planning steps)  
**Estimated effort:** 55–70 hours  
**Risk level:** High  
**Blueprint reference:** §1 (Phase 6), §5 (Phase 6), §4 (ROS2 bridge, LangGraph mention), §8 (physical safety)
→ **Test spec:** [§11 in tests.md](./tests.md#11-phase-6--agentic--robotics)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 6.1 | Implement ReAct planning loop | `services/orchestrator/src/orchestrator/core/agent_loop.py` | 10 | Loop: thought → action → observation → thought... → final answer. Configurable max iterations (default 5). LLM prompt includes "Available actions" and "Your reasoning" sections. Each iteration appends to context. Timeout per iteration (default 30s). |
| 6.2 | Create agent loop state machine extension | `services/orchestrator/src/orchestrator/core/state_machine.py` (extend) | 4 | Add TOOL_WAITING → PROCESSING (tool result received → more thinking needed) vs TOOL_WAITING → SPEAKING (tool result received → enough info to answer). Looping within TOOL_WAITING for multi-step plans. |
| 6.3 | Implement plan visualization | `services/orchestrator/src/orchestrator/core/agent_loop.py` (extend) | 3 | Stream each plan step (thought, action, observation) to client as formatted text. Show the LLM's reasoning path — not just final answer. |
| 6.4 | Create multi-step tool chaining | `services/orchestrator/src/orchestrator/core/agent_loop.py` (extend) | 4 | Tool results fed back as observations. LLM can request another tool with different args based on previous result. Max 5 iterations guard. |
| 6.5 | Create ROS2 bridge (basic) | `services/robotics/ros2_bridge/` | 12 | ROS2 (Humble/Jazzy) node package. Listens for tool call requests via MQTT or REST. Translates to ROS2 service calls. Enforces safety limits: max velocity, joint limits, forbidden zones. Sends sensor readings back as tool results. |
| 6.6 | Implement hardware safety constraints | `services/robotics/ros2_bridge/safety.py` | 4 | Velocity limits, acceleration limits, workspace boundaries, emergency stop detection. All enforced in the bridge code, not in the prompt. Log every movement command. |
| 6.7 | Create robotics tool stubs | `services/tools/src/tools/robotics.py` | 3 | `move_arm(x, y, z)`, `get_sensor_reading(sensor_name)`, `set_gripper(position)`. All "restricted" safety tier. Arguments validated against safety limits before sending to bridge. |
| 6.8 | Implement plan fallback (ReAct → simple) | `services/orchestrator/src/orchestrator/core/agent_loop.py` (extend) | 2 | If ReAct loop exceeds max iterations or times out, fall back to simple single-tool response. Log the failure. |
| 6.9 | Add agent loop metrics and monitoring | `services/orchestrator/src/orchestrator/core/agent_loop.py` (extend) | 2 | Track: loop iterations, tool calls per query, average plan depth, time per iteration. Exported as Prometheus metrics or structured logs. |
| 6.10 | Create ROS2 bridge Dockerfile | `services/robotics/Dockerfile` | 2 | ROS2 Humble base image. Non-root user. Entrypoint launches ros2 bridge node. |
| 6.11 | Create agentic integration tests | `tests/test_agentic.py` | 6 | Mock all tools. Test: multi-step plan (tool1 → result → tool2 → result → answer), max iterations guard, timeout, fallback to simple mode, error recovery. |
| 6.12 | Create robotics integration tests (simulated) | `tests/test_robotics.py` | 4 | Mock ROS2 bridge responses. Test: move command → safety constraint validation, sensor reading → structured result, emergency stop handling. Run without actual ROS2 in CI. |
| 6.13 | Create hardware-in-the-loop test harness | `scripts/robot_test.py` | 4 | Script that connects to real ROS2 bridge (when available). Runs basic movement commands within safety limits. Reports success/failure. |
| 6.14 | Add ROS2 bridge health check | `services/robotics/ros2_bridge/health.py` | 2 | `GET /health` for bridge: reports ROS2 node status, connected topics, safety limits loaded. |
| 6.15 | Document safety constraints and emergency procedures | `docs/robotics_safety.md` | 2 | Clear documentation: what physical actions the system can perform, what safety limits are enforced, how to e-stop, how to add new robotic tools safely. |

#### Parallelization Opportunities

- **6.1, 6.2, 6.3** (ReAct loop) — core agentic work, sequential within group
- **6.5, 6.6, 6.10** (ROS2 bridge) — robotics track, can be mostly parallel with 6.1-6.4
- **6.7** (robotics tools) depends on 6.5 partially (tool signatures), can start in parallel if stubs are defined
- **6.8, 6.9** (fallback + metrics) can be parallel after 6.1
- **6.11, 6.12, 6.13** must come after everything else

#### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **ReAct loop doesn't converge** — LLM keeps calling tools without reaching an answer | High — agent loops forever or hallucinates | Max iteration guard (5), timeout per iteration (30s), fallback to simple mode. These must be non-negotiable. |
| **ROS2 bridge crashes** — or ROS2 node is not available | Medium — robotics features stop, but core assistant still works | Bridge designed as isolated service; orchestrator degrades gracefully: "I'm sorry, the robotics bridge is offline." |
| **Physical damage from incorrect tool execution** | **CRITICAL** — must never happen | Safety limits enforced in bridge code (not prompt). Restricted tier with allowlist. Every movement command logged. E-stop integration. |
| **LLM hallucinates tool arguments** — passes invalid coordinates, speeds, etc. | Medium-high — could cause unexpected behavior | Schema validation at tool registry level. Safety clamp at bridge level. Two layers of defense. |
| **Multi-step plans exceed LLM context window** | Low-medium — tool results and reasoning chain take up tokens | Aggressive sliding-window per Phase 3.7. Summarize completed steps instead of keeping full trace. |

#### Done Criteria

- [ ] ReAct loop: thought → action → observation → final answer (tested with mocked tools)
- [ ] Max iteration guard (5) stops loop with fallback response
- [ ] Timeout per iteration (30s) triggers fallback
- [ ] Plan steps streamed to client as structured text
- [ ] Multi-step chaining: LLM calls tool, uses result to call different tool, produces coherent answer
- [ ] ROS2 bridge starts, connects to ROS2 DDS (or fails gracefully with logged error)
- [ ] Hardware safety constraints enforced in bridge: max velocity, joint limits, forbidden zones
- [ ] Robotics tools (`move_arm`, `get_sensor_reading`) correctly routed through bridge with safety checks
- [ ] Restricted tier for all robotics tools; allowlist required
- [ ] ROS2 bridge health endpoint reports status
- [ ] Agentic tests pass with mocked tools (6.11)
- [ ] Safety documentation exists and covers e-stop, limits, and procedures

---

### Phase 7 — Deployment

**Goal:** Docker production images, auth, observability, 24/7 daemon. Runs unattended on a home server.

**Dependencies:** Phase 3 minimum (Phase 6 ideal — deploy what exists)  
**Estimated effort:** 25–35 hours  
**Risk level:** Medium  
**Blueprint reference:** §1 (Phase 7), §7 (CI/CD), §8 (security, auth)
→ **Test spec:** [§12 in tests.md](./tests.md#12-phase-7--deployment)

#### Tasks

| # | Task | File(s) | Hours | Description |
|---|------|---------|-------|-------------|
| 7.1 | Harden Docker production images | `services/*/Dockerfile` (all) | 4 | Non-root user in all images. Minimal base (python:3.12-slim). Remove build tools from runtime. Set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`. |
| 7.2 | Create production docker-compose.yml | `docker-compose.prod.yml` | 3 | Production overrides: restart policies (`unless-stopped`), resource limits (CPU, memory), no port maps to 0.0.0.0 (only internal), health checks on all services, `.env` file loading, log driver. |
| 7.3 | Implement authentication layer | `services/orchestrator/src/orchestrator/routes/auth.py` | 4 | API key auth for REST endpoints. JWT or pre-shared key for WebSocket (§8). `validate_api_key()` middleware. Key from environment. Rate limiting per key. |
| 7.4 | Add Prometheus metrics | `services/orchestrator/src/orchestrator/metrics.py` | 4 | Expose metrics endpoint: request count+duration per route, FSM state distribution, latency histograms per pipeline stage, tool call count per tool, memory query latency. |
| 7.5 | Add structured logging to all services | `(all services)` | 3 | Ensure every service uses structlog with consistent fields: `service`, `request_id`, `session_id`, `timestamp`, `level`. Add file rotation for persistent logs. |
| 7.6 | Configure Redis persistence and password | `docker-compose.prod.yml` + Redis config | 2 | Set `requirepass` in Redis config. AOF persistence enabled. Redis config exposed via volume. |
| 7.7 | Create systemd service | `deploy/jarvis.service` | 2 | systemd unit for Docker Compose: `After=docker.service`, `Restart=always`, `ExecStartPre=docker compose pull`, `ExecStart=docker compose up`. For always-on server. |
| 7.8 | Create health check monitoring script | `scripts/health_monitor.py` | 3 | Python script: hit all service health endpoints every 30s. Alert on failure (via systemd notify, desktop notification, optional Slack/Pushover webhook). Log uptime. |
| 7.9 | Create backup strategy (memory DB) | `scripts/backup.sh` | 2 | Cron script: backup ChromaDB persistence directory + Redis AOF to timestamped archive. Keep last 7 backups. |
| 7.10 | Add rate limiting per endpoint | `services/orchestrator/src/orchestrator/middleware/rate_limit.py` | 2 | Configurable rate limits per route in `settings.yaml`. Redis-backed rate counter (sliding window). 429 response with `Retry-After` header. |
| 7.11 | Update CI/CD for deployment | `.github/workflows/deploy.yml` | 3 | GitHub Actions workflow: on merge to `main`, build + push images to GHCR, optionally SSH to home server and `docker compose pull && docker compose up -d`. |
| 7.12 | Create deployment documentation | `docs/deployment.md` | 2 | Step-by-step: prerequisites, env setup, `docker compose up`, systemd installation, backup setup, monitoring, updating. |
| 7.13 | Add security headers middleware | `services/orchestrator/src/orchestrator/middleware/security.py` | 1 | HSTS, X-Content-Type-Options: nosniff, X-Frame-Options: DENY, CSP for web UI. |
| 7.14 | Create all-hands startup/health check E2E test | `tests/test_deployment.py` | 2 | Start full stack with docker compose, verify all services healthy, run a basic voice → text → voice pipeline with mocked audio, verify response. Tear down. |
| 7.15 | Add watchdog health check container | `docker-compose.prod.yml` + `services/watchdog/` | 2 | Small container that pings all services every 30s. On detected failure: restart failed container, log incident, send notification. |

#### Parallelization Opportunities

- **7.1, 7.2** (Docker hardening + production compose) — sequential
- **7.3** (auth), **7.4** (metrics), **7.5** (logging), **7.6** (Redis) — all parallel after 7.2
- **7.7, 7.8, 7.9** (systemd, monitoring, backup) — parallel, independent
- **7.10** (rate limiting) — can be parallel with 7.3
- **7.11** (CI/CD) — can start after first images are tested
- **7.12, 7.13, 7.14** — all parallel after core deployment works

#### Risks

- **Risk**: Exposed orchestrator port without proper auth allows unauthorized access.  
  *Mitigation*: Bind to localhost/LAN only by default; auth middleware (7.3); document reverse proxy requirement for internet access.
- **Risk**: Memory (ChromaDB) data loss on container restart.  
  *Mitigation*: Docker volumes for persistence; backup script (7.9); AOF for Redis.
- **Risk**: Resource exhaustion (LLM OOM, Redis fills disk).  
  *Mitigation*: Container resource limits (7.2); monitoring with alerts (7.8); log rotation (7.5).
- **Risk**: Home server loses power and corrupts state.  
  *Mitigation*: Graceful shutdown via systemd + SIGTERM (Phase 0 already handles this). AOF persistence for Redis. Regular backups.

#### Done Criteria

- [ ] All Docker images use non-root user and slim base; no build tools in runtime
- [ ] `docker compose -f docker-compose.prod.yml up` starts full stack with resource limits
- [ ] API key / JWT auth protects all endpoints; unauthenticated requests get 401
- [ ] Prometheus metrics endpoint exposes key pipeline metrics
- [ ] All services emit structured JSON logs with consistent fields
- [ ] Redis has password protection and AOF persistence
- [ ] systemd service starts stack on boot, restarts on failure
- [ ] Health monitor runs every 30s, logs uptime, alerts on failure
- [ ] Backup cron creates daily ChromaDB + Redis snapshots (keeps 7)
- [ ] Rate limiting enforced: configurable per-route limits, 429 with `Retry-After`
- [ ] CI/CD builds images and pushes to GHCR on main merge
- [ ] Deployment documentation covers full setup from scratch
- [ ] Security headers (HSTS, nosniff, DENY frame) in middleware
- [ ] E2E deployment test starts stack, verifies health, runs basic pipeline
- [ ] Watchdog container auto-restarts failed services

---

## Overall Timeline

**Assumptions:** Solo developer working ~15-20 hours/week (evenings + weekends).  
**Hardware target:** CPU-only laptop (16GB RAM) for Phases 1-5; optional GPU for Phase 3+ latency tuning.

| Phase | Estimated Hours | Calendar Time (15h/wk) | Dependencies | Risk Level |
|-------|----------------|----------------------|--------------|------------|
| Phase 0 — Skeleton | 40h | 2.5 weeks | None | Low |
| Phase 0.5 — Audio Primitives | 20h | 1.5 weeks | Phase 0 | Low |
| Phase 1 — Text Brain | 25h | 1.5 weeks | Phase 0 | Low-Med |
| Phase 2 — Voice I/O (turn-based) | 40h | 2.5 weeks | Phase 0.5, Phase 1 | Medium |
| Phase 2.5 — Streaming (no barge-in) | 35h | 2.5 weeks | Phase 2 | Med-High |
| Phase 3 — Real-Time Streaming | 80h | 5.5 weeks | Phase 2.5 | **High** |
| Phase 4 — Memory | 40h | 2.5 weeks | Phase 3 | Medium |
| Phase 5 — Tool Calling | 35h | 2.5 weeks | Phase 3 | Medium |
| Phase 6 — Agentic + Robotics | 60h | 4 weeks | Phase 4, Phase 5 | High |
| Phase 7 — Deployment | 30h | 2 weeks | Phase 3 (min); Phase 6 (ideal) | Medium |
| **Total** | **~405h** | **~27 weeks** | | |

### Timeline Grid (Weeks 1–27)

```
Week:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27
      ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
P0    │████████████████████████████████████████████                                          │ 40h
P0.5  │    ████████████████████████                                                          │ 20h
P1    │    ██████████████████████████████████████████                                        │ 25h
P2    │        ████████████████████████████████████████████████████████████                   │ 40h
P2.5  │              ████████████████████████████████████████████████████████████████          │ 35h
P3    │                      ██████████████████████████████████████████████████████████████████│ 80h
P4    │                                                                                       │ 40h (can start wk 17)
P5    │                                                                                       │ 35h (can start wk 17)
P6    │                                                                                       │ 60h (starts wk 20)
P7    │                                                                                       │ 30h (starts wk 21)
      └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┘
```

### Optimistic Timeline (with parallelism)

If the developer can dedicate more hours or some phases are simpler than estimated:

| Phase | Optimistic | Realistic | Pessimistic |
|-------|-----------|-----------|-------------|
| Phase 0 | 2 wk | 2.5 wk | 3.5 wk |
| Phase 0.5 | 1 wk | 1.5 wk | 2 wk |
| Phase 1 | 1 wk | 1.5 wk | 2.5 wk |
| Phase 2 | 2 wk | 2.5 wk | 3.5 wk |
| Phase 2.5 | 1.5 wk | 2.5 wk | 3.5 wk |
| Phase 3 | 4 wk | 5.5 wk | 8 wk |
| Phase 4 | 2 wk | 2.5 wk | 3.5 wk |
| Phase 5 | 2 wk | 2.5 wk | 3.5 wk |
| Phase 6 | 3 wk | 4 wk | 6 wk |
| Phase 7 | 1.5 wk | 2 wk | 3 wk |
| **Total** | **20 wk** | **27 wk** | **39 wk** |

---

## Critical Path Analysis

The critical path is the longest dependency chain — any delay here directly extends the total timeline.

### Critical Path Chain

```
Phase 0 → Phase 0.5 → Phase 2 → Phase 2.5 → Phase 3 → Phase 5 → Phase 6 → Phase 7
```

**Length:** ~27 weeks (realistic), all phases on this chain are sequential — no parallelization possible.

### Why Each Phase Is on the Critical Path

| Phase | Reason |
|-------|--------|
| **Phase 0** | Foundation — everything depends on it. No shortcuts possible. |
| **Phase 0.5** | Audio primitives are prerequisite for all voice I/O. Cannot skip — per blueprint warning. |
| **Phase 2** | Turn-based voice must work before streaming can be built. |
| **Phase 2.5** | Streaming without barge-in exposes streaming bugs before real-time complexity. Per blueprint: "Do not start Phase 3 until Phase 2.5 works." |
| **Phase 3** | The hardest phase and the core of real-time conversational AI. Most pipeline components converge here. No known shortcut. |
| **Phase 5** | Tool calling is prerequisite for agentic behavior. Depends on Phase 3 FSM (TOOL_WAITING state). |
| **Phase 6** | ReAct loop + robotics is the final "smart assistant" milestone. Must follow tools and memory. |
| **Phase 7** | Deployment caps the project. Can theoretically start after Phase 3 if earlier delivery is desired. |

### What Is NOT on the Critical Path

| Phase | Off-Ramp |
|-------|----------|
| **Phase 1** | Text brain only needs Phase 0. Completed early (week 4-5). |
| **Phase 4 (Memory)** | Can be deferred until after Phase 3 without blocking anything on the critical path. Memory enriches the assistant but the core pipeline works without it. **If timeline pressure hits, Phase 4 is the safest to delay.** |
| **Phase 7 (Deployment)** | Can start after Phase 3 if you want the system running 24/7 before agentic features are done. The deployment phase is somewhat independent once the core pipeline is stable. |

### Critical Path Acceleration Options

1. **Phase 0.5 + Phase 1 in parallel** (weeks 2-4): Audio primitives and text brain have no dependency on each other beyond Phase 0. This saves ~1 week.
2. **Phase 4 + Phase 5 in parallel** (both start after Phase 3): No dependency between memory and tools. This saves ~2.5 weeks off the total if both were sequential.
3. **Phase 7 starting after Phase 3** (instead of Phase 6): Deployment can happen earlier if 24/7 operation is a priority over agentic features. Saves ~6 weeks off the "full system" timeline if agentic is deferred.

---

## Parallelization Strategy

### Phase-Level Parallelism

| Parallel Group | Phases | Rationale | Weeks |
|---------------|--------|-----------|-------|
| **Group A** | Phase 0.5 + Phase 1 | Audio primitives and text brain are independent after Phase 0 | 2-4 |
| **Group B** | Phase 4 + Phase 5 | Memory and tools are independent after Phase 3 | 17-20 |
| **Group C** | Phase 6 + Phase 7 (partial) | Deployment hardening can start while agentic features are being polished. Phase 6 tools (ROS2) are independent of Docker/auth work. | 21-27 |

### Intra-Phase Parallelization (summarized from each phase above)

| Phase | Parallel Streams |
|-------|-----------------|
| Phase 0 | Infra group, config group, shared package, service skeletons, Docker/CI |
| Phase 0.5 | Mic implementation ↔ File source implementation; tests after both |
| Phase 1 | LLM client ↔ System prompt; Docker independent |
| Phase 2 | STT group ↔ TTS group; auth in parallel |
| Phase 2.5 | VAD ↔ WebSocket endpoint; streaming STT ↔ streaming LLM forwarding |
| Phase 3 | FSM ↔ wake word ↔ sentence-chunked TTS (all independent); concurrent I/O + barge-in after FSM |
| Phase 4 | Short-term buffer ↔ Long-term ChromaDB (fully independent) |
| Phase 5 | Tool registry → individual tools (all parallel); pipeline integration after |
| Phase 6 | ReAct loop ↔ ROS2 bridge (independent tracks) |
| Phase 7 | Docker hardening ↔ auth ↔ metrics ↔ logging (all parallel) |

### Recommended Work Plan (Weeks 1-27)

```
Week 1:  Phase 0 — monorepo, .gitignore, docker-compose, config/settings
Week 2:  Phase 0 — shared/ package (messages, config, state, logging), service skeletons
Week 3:  Phase 0 — Dockerfiles, CI, tests; Phase 0.5 — audio abstractions
Week 4:  Phase 0.5 — WAV fixtures, tests; Phase 1 — LLM client, system prompt
Week 5:  Phase 1 — /chat endpoint, CLI client, tests
Week 6:  Phase 2 — STT service + faster-whisper
Week 7:  Phase 2 — TTS service + Piper, Kokoro; Phase 2 — WebSocket auth
Week 8:  Phase 2 — Turn-based client, /voice endpoint, integration tests
Week 9:  Phase 2.5 — WebSocket endpoint, streaming client, VAD
Week 10: Phase 2.5 — Streaming STT with partials, LLM token forwarding
Week 11: Phase 2.5 — Full-utterance TTS, pipeline coordinator, integration tests
Week 12: Phase 3 — FSM implementation
Week 13: Phase 3 — Wake word, sentence-chunked TTS
Week 14: Phase 3 — Barge-in, concurrent I/O
Week 15: Phase 3 — Cold-start, sliding window, listening timeout
Week 16: Phase 3 — VAD integration, TOOL_WAITING state, ERROR recovery
Week 17: Phase 3 — Latency tests, barge-in tuning, regression tests
Week 18: Phase 4 — Short-term buffer, ChromaDB setup; Phase 5 — Tool registry, starter tools
Week 19: Phase 4 — Fact extraction, memory injection; Phase 5 — Schema converter, tools service
Week 20: Phase 4 — Integration tests; Phase 5 — Confirmation flow, allowlist, tests
Week 21: Phase 6 — ReAct loop; Phase 7 — Docker hardening, production compose
Week 22: Phase 6 — ROS2 bridge; Phase 7 — Auth, metrics
Week 23: Phase 6 — Robotics tools, safety; Phase 7 — systemd, monitoring
Week 24: Phase 6 — Agent integration tests; Phase 7 — CI/CD deploy
Week 25: Phase 6 — Safety tests, documentation; Phase 7 — E2E deployment test
Week 26: Buffer / latency tuning / prompt iteration / bug fixes
Week 27: Final integration, system-wide E2E tests, stretch goals
```

---

## Top 5 Risks

| # | Risk | Impact | Likelihood | Phase | Mitigation |
|---|------|--------|------------|-------|------------|
| **R1** | **Phase 3 real-time streaming latency unacceptable on target hardware** | High — assistant feels broken, voice-to-voice >3s | High (CPU-only laptop may not meet <1.5s budget) | Phase 3 | Measure latency per stage early (task 3.13). Identify bottleneck. If CPU LLM is the bottleneck, cloud fallback for LLM only (keep STT/TTS local). Accept 2-3s as "functional" for v1. Document GPU upgrade path. |
| **R2** | **Barge-in implementation unreliable: too aggressive or too lenient** | High — worst case, user can never interrupt or assistant constantly cuts off | Medium | Phase 3 | Configurable chunk size (50-400ms). Dedicated tuning experiment (3.15). Default to conservative behavior (longer chunks, less responsive interrupt) for v1, tune later. |
| **R3** | **Local free-tier LLM quality insufficient for tool calling and agentic planning** | Medium — tools are called wrong, ReAct loops don't converge | Medium-High | Phases 5, 6 | Use Groq/Gemini free tier as LLM backend (faster, smarter) for tool-calling tasks. Keep Ollama for simple conversations. Router pattern: easy → local, hard → cloud. |
| **R4** | **Integration complexity overwhelms solo developer — debugging distributed audio pipelines across 5+ services** | High — developer burnout, stalled progress | Medium | Phase 3+ | Use structlog from Phase 0. Implement comprehensive logging with request_id tracing. Create integration tests early. Each phase produces working (if limited) end-to-end system per §2 principle #3. |
| **R5** | **Physical safety incident from robotics control (Phase 6)** | **Critical** — hardware damage or injury | Low | Phase 6 | Safety limits enforced in bridge code (not prompt). Restricted tier with allowlist. All movement commands logged. E-stop button required. Test with simulated robot before real hardware. Start with read-only sensors before actuators. |

### Risk Mitigation Investment

| Risk | Prevention Hours | Detection Method | Recovery |
|------|-----------------|-----------------|----------|
| R1 (Latency) | 4h (benchmark scripts) | Latency regression tests (3.13) | Cloud LLM fallback |
| R2 (Barge-in) | 4h (tuning experiment 3.15) | Manual UX testing | Conservative defaults |
| R3 (LLM quality) | 2h (cloud fallback config) | Tool call accuracy tests | Route to Groq/Gemini |
| R4 (Integration) | 10h (structlog + tests across phases) | Integration test suite | Phase isolation debugging |
| R5 (Safety) | 8h (bridge safety code, tests) | Safety constraint validation tests | E-stop, physical disconnect |

---

## Effort Summary

### Per-Phase Effort

| Phase | Hours (Low) | Hours (High) | Risk Level | Output |
|-------|-------------|-------------|------------|--------|
| Phase 0 — Skeleton | 35 | 45 | Low | Repo, Docker, config, shared/ package, CI |
| Phase 0.5 — Audio Primitives | 16 | 22 | Low | AudioSource/Sink, WAV fixtures, tests |
| Phase 1 — Text Brain | 22 | 28 | Low-Med | LLM client, /chat, CLI, system prompt |
| Phase 2 — Voice I/O (turn-based) | 36 | 46 | Medium | STT, TTS, turn-based voice pipeline |
| Phase 2.5 — Streaming (no barge-in) | 30 | 38 | Med-High | WebSocket streaming, VAD, partials |
| Phase 3 — Real-Time Streaming | 70 | 90 | **High** | FSM, wake word, barge-in, chunked TTS |
| Phase 4 — Memory | 35 | 45 | Medium | Redis buffer, ChromaDB, fact extraction |
| Phase 5 — Tool Calling | 30 | 40 | Medium | Registry, 4 tools, safety tiers |
| Phase 6 — Agentic + Robotics | 55 | 70 | **High** | ReAct loop, ROS2 bridge, safety |
| Phase 7 — Deployment | 25 | 35 | Medium | Docker prod, auth, metrics, 24/7 |
| **Total** | **354** | **459** | | |

### Cumulative Effort Curve

```
Hours
500 ┤
    │                                          ● Phase 6-7 (405-459h)
450 ┤                                     ●──
    │                                ●──
400 ┤                           ●──
    │                      ●──
350 ┤                 ●──
    │            ●──
300 ┤       ●──
    │  ●──
250 ┤ ●── Phase 0-1 (57-73h)
    │
200 ┤
    │
150 ┤
    │
100 ┤
    │
 50 ┤
    │
  0 └────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────
        P0  P0.5 P1   P2  P2.5  P3   P4   P5   P6   P7
```

### Milestone Summary

| Milestone | Phases | Cumulative Hours | Calendar (realistic) |
|-----------|--------|-----------------|---------------------|
| 🟢 **Skeleton done** | Phase 0 | ~40h | Week 2.5 |
| 🟢 **Audio I/O works** | Phase 0.5 | ~60h | Week 4 |
| 🟢 **Text chat works** | Phase 1 | ~85h | Week 5 |
| 🟢 **Turn-based voice works** | Phase 2 | ~125h | Week 8 |
| 🟢 **Streaming voice works (no interrupt)** | Phase 2.5 | ~160h | Week 10 |
| 🟡 **Real-time conversation works** | Phase 3 | ~240h | Week 16 |
| 🟡 **Assistant remembers** | Phase 4 | ~280h | Week 18 |
| 🟡 **Assistant can use tools** | Phase 5 | ~315h | Week 20 |
| 🔴 **Agentic + robotics works** | Phase 6 | ~375h | Week 24 |
| 🔴 **Runs 24/7 in production** | Phase 7 | ~405h | Week 27 |

### Key Insight: Minimum Viable "Feels Like Jarvis" Timeline

If you stop after **Phase 3** (real-time streaming) and skip Phases 4-6 initially:
- **Total: ~240 hours / ~16 weeks**
- You get: wake word, real-time voice conversation, streaming STT/LLM/TTS, barge-in
- You **don't** get: memory, tools, agentic behavior, robotics, 24/7 deployment
- This is the earliest point where the assistant *feels like a conversation*

From there, Phases 4-7 add superpowers in any order:
- Phase 4 (memory) for continuity across days
- Phase 5 (tools) for web search, file access
- Phase 6 (agentic) for multi-step reasoning and robotics
- Phase 7 (deployment) for always-on operation

---

## Appendix: Quick Reference

### File Count by Phase

| Phase | New Files | Modified Files | Key Directories |
|-------|----------|---------------|-----------------|
| Phase 0 | ~30 | 0 | `shared/`, `services/*/`, `config/`, `scripts/`, `tests/` |
| Phase 0.5 | ~5 | 1 | `shared/src/shared/audio.py`, `tests/fixtures/` |
| Phase 1 | ~8 | ~3 | `services/orchestrator/clients/`, `routes/`, `core/` |
| Phase 2 | ~12 | ~5 | `services/stt/`, `services/tts/`, `orchestrator/routes/` |
| Phase 2.5 | ~8 | ~6 | `orchestrator/routes/ws.py`, `stt/vad.py` |
| Phase 3 | ~10 | ~12 | `orchestrator/core/state_machine.py`, `tts/chunker.py` |
| Phase 4 | ~10 | ~5 | `services/memory/`, `orchestrator/clients/memory.py` |
| Phase 5 | ~12 | ~6 | `services/tools/`, `orchestrator/clients/tools.py` |
| Phase 6 | ~12 | ~5 | `services/robotics/`, `orchestrator/core/agent_loop.py` |
| Phase 7 | ~12 | ~10 | `deploy/`, `services/watchdog/`, middleware files |
| **Total** | **~119** | **~53** | |

### Key Technologies by Phase

| Phase | Key Technologies |
|-------|-----------------|
| Phase 0 | Python 3.12, FastAPI, Pydantic v2, structlog, Docker, Docker Compose, Redis |
| Phase 0.5 | sounddevice, WAV, numpy, scipy |
| Phase 1 | Ollama API (httpx), SSE streaming |
| Phase 2 | faster-whisper, Piper TTS, Kokoro TTS, WebSocket |
| Phase 2.5 | WebSocket, Silero VAD, async streaming |
| Phase 3 | openWakeWord, Silero VAD, asyncio, FSM pattern |
| Phase 4 | Redis (async), ChromaDB, Ollama embeddings (nomic-embed-text) |
| Phase 5 | Instructor, DuckDuckGo/SearXNG, PyMuPDF, python-docx |
| Phase 6 | ROS2 (Humble/Jazzy), MQTT, ReAct pattern |
| Phase 7 | Prometheus, systemd, GitHub Actions, GHCR |

---

*End of schedule. Last updated: 2026-07-29.*  
*Sources: `jarvis_blueprint.md` (485 lines), architectural analysis, industry latency benchmarks for local ML inference.*
