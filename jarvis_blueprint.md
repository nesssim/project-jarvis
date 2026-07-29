# Project J.A.R.V.I.S. — Personal AI Voice Assistant
## Full Engineering Blueprint (Free-First, Pay-to-Scale)

---

## 0. Design Philosophy

Four principles drive every decision below:

1. **Local-first, cloud-optional.** Every core capability must have a $0 path that runs on your own hardware. Paid services are *accelerants*, never *requirements*.
2. **Decoupled pipeline.** STT, LLM reasoning, memory, tools, and TTS are separate services communicating over a message bus / API, not one monolithic script. This lets you swap Whisper for Deepgram later without touching anything else.
3. **Build in vertical slices, not horizontal layers.** Each phase below produces a *working end-to-end assistant*, just a dumber one. You never have an unintegrated pile of parts.
4. **Latency is a first-class feature, not an afterthought.** A "smart" assistant with a 6-second response time feels broken. Architecture choices from Phase 1 onward are made with a <1.5s voice-to-voice budget in mind (see §6).

---

## 1. Phased Roadmap

| Phase | Goal | New Components | "Done" Criteria |
|---|---|---|---|
| **0** | Repo & infra skeleton | Git, Docker, config system, logging, health checks | `docker compose up` boots an empty service mesh |
| **0.5** | Audio primitives | AudioSource/AudioSink abstractions, WAV test fixtures | Audio I/O works in isolation with mockable sources and sinks |
| **1** | Text brain | LLM client, system prompt, CLI chat loop | You can type a question, get a coherent streamed answer |
| **2** | Voice in/out | STT (Whisper), TTS (Piper/Kokoro), audio I/O | You can speak, hear a spoken reply (turn-based, not real-time) |
| **2.5** | Streaming without barge-in | WebSocket streaming audio, streaming STT partials, streaming LLM, full-utterance TTS | User speaks (no keypress), sees/hears streaming text, waits for full audio response |
| **3** | Real-time streaming | VAD, wake word, formal orchestrator state machine, streaming STT->LLM->TTS pipeline, barge-in | Feels like a conversation, not a walkie-talkie |
| **4** | Memory | Short-term (session buffer) + long-term (vector DB) | Assistant recalls facts from days-old conversations |
| **5** | Tool calling | Function-calling layer, web search, file I/O, APIs | "What's the weather, and email it to me" works |
| **6** | Agentic + robotics | Planner/executor loop, ROS2 bridge, device control | "Turn on the desk lamp and check my build status" works |
| **7** | Deployment & hardening | Always-on daemon, CI/CD, auth, observability | Runs 24/7 unattended on a home server / Pi cluster |

Build strictly in this order. Do not skip Phase 0.5 (audio primitives) — knowing audio I/O works in isolation saves days of debugging later. Do not start Phase 3 streaming until Phase 2.5's streaming-without-barge-in works — streaming bugs are much harder to debug on top of an unstable base.

---

## 2. Logical Architecture

```
                              ┌────────────────────────────┐
                              │        Wake Word /          │
                              │   Voice Activity Detection   │
                              └───────────┬──────────────────┘
                                          │ audio stream
                              ┌───────────▼──────────────────┐
                              │      STT (Speech->Text)        │
                              │   streaming, partial results   │
                              └───────────┬──────────────────┘
                                          │ text (partial + final)
                     ┌────────────────────▼─────────────────────┐
                     │              ORCHESTRATOR (core)           │
                     │  - state machine (IDLE, LISTENING, ...)    │
                     │  - prompt assembly                           │
                     │  - routes to LLM, injects memory & tool ctx  │
                     └───┬───────────────┬───────────────┬─────────┘
                         │               │               │
          ┌──────────────▼───┐ ┌─────────▼────────┐ ┌────▼─────────────┐
          │   Memory Layer     │ │   LLM Reasoning    │ │  Tool Registry     │
          │ - short-term buf   │ │ - local (Ollama) or │ │ - web search        │
          │ - long-term vector │ │   cloud API          │ │ - file read/analyze │
          │   DB (episodic +   │ │ - function-calling    │ │ - calendar/email    │
          │   semantic memory) │ │   capable model        │ │ - smart home        │
          └────────────────────┘ └───────────┬─────────┘ │ - robotics/ROS2 bridge│
                                              │           └──────────────────────┘
                                   text response (streamed)
                                              │
                              ┌───────────────▼───────────────┐
                              │        TTS (Text->Speech)        │
                              │   streaming, low first-byte lat  │
                              └───────────────┬───────────────┘
                                              │ audio stream
                              ┌───────────────▼───────────────┐
                              │      Speaker Output / Client     │
                              └───────────────────────────────┘
```

**Key architectural decision: everything talks over a local message bus (Redis Streams with consumer groups), not direct function calls.** Redis Streams support consumer groups (each service consumes independently), message acknowledgment (no lost messages on crash), replay (debugging by replaying a session), and natural backpressure (consumers read at their own pace). This means:
- The orchestrator doesn't care if STT is local Whisper or cloud Deepgram — it just consumes a `transcript` event.
- You can run each service as its own Docker container, on its own machine (e.g., LLM on a GPU box, TTS on the Pi near your speakers), or all on one laptop.
- Swapping any single component later (Phase-gate upgrade) touches zero other code.
- Each service exposes a `GET /health` endpoint for monitoring (`{"status": "ok", "dependencies": {"redis": true, "ollama": true}}`).

### 2.1 Message Protocol

All services communicate over Redis Streams using a shared, typed message protocol defined via Pydantic models:

**Message type enum:**
- `TRANSCRIPT_PARTIAL` — Partial STT result during speech
- `TRANSCRIPT_FINAL` — Finalized utterance transcription
- `VAD_SPEECH_START` — User started speaking
- `VAD_SPEECH_END` — User stopped speaking
- `TTS_SYNTHESIZE` — Request TTS to synthesize text
- `TTS_STOP` — Interrupt ongoing TTS playback
- `TTS_AUDIO_CHUNK` — Streamed audio chunk from TTS
- `TTS_COMPLETE` — TTS finished playback
- `LLM_GENERATE` — Request LLM to generate a response
- `LLM_CANCEL` — Cancel an in-flight LLM generation
- `LLM_TOKEN` — Individual token from LLM stream
- `LLM_COMPLETE` — LLM finished generation
- `LLM_TOOL_CALL` — LLM issued a tool call request
- `MEMORY_STORE` — Request to store in long-term memory
- `MEMORY_RETRIEVE` — Request to retrieve from memory
- `MEMORY_RETRIEVE_RESULT` — Memory retrieval results

Each message envelope includes:
- `type: MessageType` — Discriminated union tag
- `payload: dict` — Type-specific payload (transcript text, audio bytes, tool arguments, etc.)
- `request_id: str` — Correlation ID for tracing a request across services
- `timestamp: float` — Unix timestamp for latency measurement and ordering

The shared Pydantic models live in `shared/src/shared/messages.py` and are imported by every service.

---

## 3. Physical Architecture

### Free-tier physical setup (single machine)
```
┌─────────────────────────────────────────────┐
│  Your PC / Laptop (16GB+ RAM ideally, GPU optional) │
│                                                 │
│  ┌───────────┐ ┌───────────┐ ┌──────────────┐ │
│  │  Docker    │ │  Docker    │ │   Docker      │ │
│  │  Ollama    │ │  Whisper   │ │   Piper TTS   │ │
│  │  (LLM)     │ │  (STT)     │ │               │ │
│  └───────────┘ └───────────┘ └──────────────┘ │
│  ┌────────────────────────────────────────┐   │
│  │  Orchestrator (Python/FastAPI) + Redis   │   │
│  └────────────────────────────────────────┘   │
│  Mic + Speaker (USB or built-in)               │
└─────────────────────────────────────────────┘
```

### Scaling-up physical setup (Phase 6-7, still mostly free)
```
Home network (LAN):
 ├── Server/Mini-PC (always-on) — Orchestrator, Redis, vector DB, Ollama
 │     (or a used RTX 3060/3090 box if you want fast local LLM inference)
 ├── Raspberry Pi 4/5 near your desk — mic array + speaker, wake word, streams audio to server
 ├── Raspberry Pi / Jetson Nano — robotics bridge (ROS2 node), talks to orchestrator over MQTT
 └── Router — mDNS/local DNS so devices find each other by hostname
```

This mirrors exactly how real Jarvis-style systems are built: a **central brain** (orchestrator + LLM) and **thin edge clients** (mic/speaker pucks, robot controllers) that just stream audio/sensor data in and receive commands out.

---

## 4. Most Efficient Free Stack

| Layer | Free/Local Choice | Why |
|---|---|---|
| **LLM (reasoning)** | Ollama running **Qwen2.5-14B-Instruct** or **Llama 3.1-8B-Instruct** (upgrade to 70B if you have the VRAM); fallback to **Groq free tier** (Llama 3.3-70B, extremely fast) or **Google Gemini Flash free tier** for when local hardware is too slow | Ollama = zero cost, full privacy, good function-calling support. Groq free tier gives near-instant cloud inference when you need more brains than your GPU has |
| **STT** | **faster-whisper** (CTranslate2-optimized Whisper) running locally, `small` or `medium` model | Real-time-capable on CPU, no API cost, good accuracy |
| **Wake word** | **openWakeWord** (fully free/open) or Porcupine free tier (limited free wake words) | Runs on-device, near-zero latency, no cloud call needed just to "wake up" |
| **VAD (voice activity detection)** | **Silero VAD** | Tiny, fast, lets you detect end-of-speech for natural turn-taking and enables barge-in |
| **TTS** | **Piper TTS** (very fast, decent quality, fully local) — alternative: **Kokoro** (lightweight, good quality) or **XTTS-v2** for more natural/cloneable voice at higher latency cost | Piper streams audio almost instantly and is the default; Kokoro offers a good quality-to-weight trade-off; XTTS sounds more human but is heavier |
| **Orchestration/backend** | **Python 3.12 + FastAPI** + **Redis** (Streams as message bus + short-term memory cache) | FastAPI gives you async WebSocket streaming natively; Redis Streams support consumer groups, message acknowledgment, replay, and backpressure |
| **Agent/tool framework** | **Instructor** (lightweight Pydantic-based tool calling) for structured extraction and tool use; only adopt **LangGraph** if multi-step planning complexity demands it | Start with Instructor — it is just Pydantic validation around LLM responses, zero overhead. LangGraph adds a graph executor that helps once you have complex branching agent loops in Phase 6 |
| **Long-term memory (vector DB)** | **ChromaDB** (embedded, local, free) with **nomic-embed-text** or **bge-small** embeddings via Ollama. Monitor query latency — if consistently above 100ms, migrate to **PostgreSQL + pgvector** | Zero infra, file-based persistence, fast enough for personal-scale memory. The 100ms threshold is a trigger to move to a more scalable store |
| **Short-term memory** | Redis list / sliding window in orchestrator | Just the last N turns + running summary |
| **Web search tool** | **SearXNG** self-hosted (primary, full control), fallback to **DuckDuckGo HTML search** (no API key) | SearXNG gives you full control over search sources and privacy; DDG is a zero-setup fallback that works anywhere |
| **File analysis** | Local Python (PyMuPDF, python-docx, pandas) triggered as a tool | No cloud dependency for reading your own files |
| **Robotics bridge** | **ROS2** (Humble/Jazzy) + a lightweight MQTT or REST bridge from the orchestrator | Industry standard, huge community, works with almost any robot |
| **Frontend/client** | Start CLI -> simple local web UI (React + WebSocket) -> optional Electron desktop app | Progressive complexity, matches your phased plan |
| **Message schemas** | **Pydantic v2** across all services | Message schemas via BaseModel, config validation via Settings, request/response serialization — shared package consumed by every service |
| **Structured logging** | **structlog** | Structured JSON logging from day one, critical for debugging distributed audio-timing issues across services |
| **Async HTTP** | **httpx** | Async HTTP client for service-to-service calls and external tool execution; used by orchestrator to call LLM APIs and by tools for web requests |
| **Audio I/O** | **sounddevice** | Cross-platform audio capture (mic) and playback (speaker) for local client; wraps PortAudio, works with any USB mic or built-in audio |
| **Containerization** | Docker + Docker Compose | One `docker-compose.yml` spins up the whole stack reproducibly |
| **CI/CD** | GitHub Actions (free for public/private repos within limits) | Lint, test, build images, and optionally auto-deploy to your home server via SSH/Watchtower |

### Minimum viable hardware for the free stack
- CPU-only laptop (8+ cores, 16GB RAM): works for Phases 1-5 with small/medium models, STT and TTS run comfortably, LLM inference will be "acceptable, not snappy" (2-5s for medium prompts).
- Add any NVIDIA GPU with 8GB+ VRAM: full real-time feel becomes achievable locally.
- No GPU at all: lean on Groq/Gemini free tiers for the LLM step only, keep STT/TTS local (they're cheap on CPU) — this is actually a very good hybrid for a truly free but fast build.

---

## 5. Detailed Component Design by Phase

### Phase 0 — Skeleton

- Monorepo structure:
  ```
  jarvis/
  ├── docker-compose.yml
  ├── docker-compose.override.yml
  ├── .env.example
  ├── .gitignore
  ├── .dockerignore
  ├── config/
  │   ├── settings.yaml
  │   ├── settings.schema.json
  │   └── prompts/
  │       ├── v1_system.md
  │       └── tools/
  │           ├── web_search.md
  │           └── read_file.md
  ├── shared/                     # Shared Pydantic models
  │   ├── pyproject.toml
  │   └── src/shared/
  │       ├── messages.py
  │       ├── config.py
  │       ├── state.py
  │       ├── audio.py
  │       └── logging.py
  ├── services/
  │   ├── orchestrator/
  │   │   ├── Dockerfile
  │   │   ├── pyproject.toml
  │   │   └── src/orchestrator/
  │   │       ├── main.py
  │   │       ├── routes/ (chat.py, ws.py)
  │   │       ├── core/ (state_machine.py, pipeline.py, prompt.py)
  │   │       └── clients/ (llm.py, memory.py, tools.py)
  │   ├── stt/
  │   │   ├── Dockerfile
  │   │   ├── pyproject.toml
  │   │   └── src/stt/ (main.py, whisper_stt.py, vad.py)
  │   ├── tts/
  │   │   ├── Dockerfile
  │   │   ├── pyproject.toml
  │   │   └── src/tts/ (main.py, piper_tts.py, kokoro_tts.py)
  │   ├── memory/
  │   │   ├── Dockerfile
  │   │   ├── pyproject.toml
  │   │   └── src/memory/ (main.py, short_term.py, long_term.py, extraction.py)
  │   └── tools/
  │       ├── Dockerfile
  │       ├── pyproject.toml
  │       └── src/tools/ (main.py, registry.py, web_search.py, file_io.py)
  ├── scripts/ (dev.sh, lint.sh, test.sh)
  ├── tests/ (conftest.py, test_conversation.py, test_latency.py)
  └── .github/workflows/ci.yml
  ```

- Config-driven, not hardcoded: every model/provider choice lives in `settings.yaml` so swapping free->paid later is a one-line change. Settings are validated at startup by Pydantic Settings — the application fails immediately if a required provider key is missing.
- Structured logging (JSON via structlog) from day one — you will need this to debug audio-timing bugs in Phase 3.
- **Every service exposes a GET /health endpoint** returning `{"status": "ok", "dependencies": {"redis": true, "ollama": true}}` with the service's critical dependencies. This is used by Docker health checks and orchestrator monitoring.
- **Rate limiting middleware** on all FastAPI routes from Phase 0. Configure per-endpoint limits in `settings.yaml`. This prevents runaway loops (e.g., STT sending thousands of partials) during development.
- **Graceful shutdown**: every service handles SIGTERM by completing in-flight work, acknowledging pending messages, closing connections, and then exiting. This prevents data loss and orphaned audio streams during restarts.

### Phase 0.5 — Audio Primitives

Before wiring voice through the full pipeline, build and test the audio I/O layer in isolation:

- **AudioSource abstraction**: interface that produces bytes from a microphone (`MicrophoneAudioSource`). Mockable as `FileAudioSource` (reads from a WAV file on disk) for deterministic testing.
- **AudioSink abstraction**: interface that consumes bytes to a speaker (`SpeakerAudioSink`). Mockable as `NullAudioSink` (discards bytes, counts them for latency measurement) for testing.
- **Test fixtures**: 3-5 short WAV files (1-5 seconds each) with known transcriptions, different sample rates (16kHz, 44.1kHz), and varying audio characteristics (quiet speech, loud speech, background noise).
- **Unit tests** at the audio abstraction level: verify capture produces expected byte counts, playback accepts valid audio formats, null sink discards correctly, file source reads complete files.
- All audio primitives live in `shared/src/shared/audio.py` so both the orchestrator client and integration tests can use them.

Done criteria: `pytest tests/ --audio` runs against real mic/speaker (when available) and passes. Audio I/O is verified to work before any STT or TTS service exists.

### Phase 1 — Text Brain
- Single FastAPI endpoint `/chat` that streams tokens (Server-Sent Events or WebSocket) from Ollama.
- System prompt v1 (see §8) establishes persona, tone, and response-length discipline (Jarvis is *concise*, not chatty).
- CLI client for testing — just `stdin` -> API -> streamed `stdout`.

### Phase 2 — Voice I/O (turn-based)
- Record on keypress -> faster-whisper transcribes full utterance -> send to Phase 1 pipeline -> full text response -> Piper synthesizes -> play audio.
- This phase is intentionally *not* real-time. Get correctness first: are transcriptions accurate, does the voice sound acceptable, is the round trip under ~4s.
- WebSocket connections from Phase 2 onward require a simple session token or API key passed in the connection request header.

### Phase 2.5 — Streaming without Barge-in

This phase introduces streaming from mic to speaker but without the complexity of concurrent I/O or interruption:

- WebSocket-based streaming audio input (no keypress — continuous capture).
- Streaming STT with partial transcripts (use Silero VAD for endpointing, emit partials as the user speaks).
- Streaming LLM response (stream tokens to the client as they arrive, but do not sentence-chunk for TTS yet).
- Full utterance TTS: wait for the complete LLM response, then synthesize and play the entire utterance. The user sees streaming text but hears only complete responses.
- NO barge-in yet — if the user speaks during playback, that audio is simply lost (recorded but discarded).
- NO concurrent audio I/O — audio input and output still operate sequentially (stop recording, play response, start recording again).
- This phase exposes streaming bugs (disconnects, partial frame handling, backpressure) without the harder barge-in bugs on top.

Done criteria: User speaks without pressing a key, sees streaming transcription on screen, receives a complete spoken response after the LLM finishes.

### Phase 3 — Real-Time Streaming

This is the hardest engineering phase. The orchestrator runs a formal state machine with well-defined transitions:

**States:** IDLE, LISTENING, PROCESSING, SPEAKING, INTERRUPTED, TOOL_WAITING, ERROR

**Transitions:**
- IDLE -> LISTENING (wake word / VAD trigger)
- LISTENING -> IDLE (timeout / no speech detected — speak "I didn't catch that")
- LISTENING -> PROCESSING (end-of-speech detected)
- PROCESSING -> SPEAKING (first sentence ready from TTS)
- PROCESSING -> TOOL_WAITING (LLM issues tool call)
- TOOL_WAITING -> PROCESSING (tool result received)
- SPEAKING -> INTERRUPTED (VAD detects user speech during playback)
- INTERRUPTED -> LISTENING (immediately, barge-in)
- ANY -> ERROR (component failure)
- ERROR -> IDLE (after recovery / timeout)

The LISTENING state has a configurable timeout (default: 5 seconds, set in `settings.yaml`). If no speech is detected within the window, the state machine transitions to IDLE and the orchestrator produces a "I didn't catch that" prompt. The timeout is distinct from VAD's silence threshold — this is a user-facing patience timer.

**Key techniques:**
- **Streaming STT**: emit partial transcripts continuously; only finalize an utterance after Silero VAD detects ~600-800ms of silence.
- **Sentence-chunked TTS**: don't wait for the full LLM response — synthesize and play each completed sentence as it streams in from the LLM. This alone cuts perceived latency by 60-70%.
- **Barge-in with jitter control**: use small TTS chunks (200ms each). When barge-in fires (VAD detects user speech), the current chunk finishes playing then playback stops. This prevents the jarring audio cut that naive instant-stop produces while still being responsive to interruption.
- **Cold-start strategy**: run a warm-up sequence on boot (a dummy request to Ollama) to load model weights into memory and trigger any JIT compilation. Use Ollama's `keep_alive: -1` to keep models loaded between requests, eliminating the 1-3s cold-start penalty on every first query after idle.
- **Sliding-window prompt truncation**: trim oldest turns from the conversation buffer before exceeding the LLM context window. Drop whole turns (question + answer pairs), never truncate mid-response. This preserves conversational coherence while staying within model limits.
- **TOOL_WAITING state**: when the state machine enters TOOL_WAITING, the UI should indicate "running a tool" (e.g., a subtle thinking sound or visual cue) so the user knows the assistant is doing work, not stuck.

**Latency budget target:**
  | Stage | Target | Notes |
  |---|---|---|
  | End of user speech -> first STT partial | <150ms | Time-to-first-token (TTFT) for audio |
  | Final transcript -> first LLM token | <300ms | LLM TTFT |
  | Between subsequent LLM tokens | ~30-50ms/token | Time-between-tokens (TBT) |
  | First LLM sentence -> first TTS audio byte | <200ms | TTS TTFT |
  | **Total perceived latency** | **<1.2-1.5s** | Voice-to-voice, end-to-end |

### Phase 4 — Memory
- **Short-term**: rolling window of last ~10-20 turns, kept in Redis, injected verbatim into the prompt.
- **Long-term**: after each session (or every N turns), summarize + embed key facts ("user's dog is named Max", "user is working on a robotics project called X") into ChromaDB. On each new query, do a semantic search against long-term memory and inject top-k relevant facts into the system prompt.
- **Memory write policy matters more than retrieval**: use a small, cheap LLM call ("is this worth remembering long-term? extract facts as JSON") after each turn rather than dumping raw transcripts into the vector DB — this keeps retrieval signal-to-noise high.
- Use the typed message protocol for memory operations: `MEMORY_STORE`, `MEMORY_RETRIEVE`, `MEMORY_RETRIEVE_RESULT` messages flow over Redis Streams, keeping the memory service decoupled from the orchestrator.

### Phase 5 — Tool Calling
- Use your LLM's native function-calling format (Qwen2.5, Llama 3.1, and Gemini/Groq models all support OpenAI-style tool schemas).
- Tool registry pattern: each tool is a Python function + a Pydantic model for argument validation, registered in one place, auto-injected into the LLM's available-tools list.
- Start with 3 tools: `web_search`, `read_file`, `get_datetime`. Expand from there.
- Guardrail: always show/log which tool was called and with what arguments — critical for debugging and for safety once tools can take real-world actions.
- **Tool safety tiers** (see also §8):
  - **Safe** (auto-execute): `get_datetime`, `web_search`, `read_file`
  - **Confirm** (speak "Shall I proceed?"): `send_email`, `write_file`, `delete_file`
  - **Restricted** (must be in allowlist, no exceptions): `execute_command`, `modify_system`, `control_hardware`
- Use the `TOOL_WAITING` state in the orchestrator (see Phase 3) to signal tool execution to the user.

### Phase 6 — Agentic + Robotics
- Move from single tool-call turns to a **plan -> act -> observe -> replan loop** (ReAct-style): the LLM can chain multiple tool calls before responding, and sees the result of each before deciding the next step.
- Robotics: expose robot capabilities as tools too (`move_arm(x,y,z)`, `get_sensor_reading(name)`) via a ROS2 bridge node that translates tool calls into ROS2 topic/service calls. The LLM never talks to ROS2 directly — always through this bridge, so you can enforce safety limits (e.g., max velocity, forbidden zones) in code, not in the prompt.
- **Safety principle**: any tool that causes a physical or irreversible action (moving hardware, sending an email, deleting a file) should require either (a) a confirmation step spoken back to you, or (b) an explicit allow-list — never let the LLM freely execute high-risk actions on trust alone.

### Phase 7 — Deployment
- Package each service as a Docker image; `docker-compose.yml` (or later, a lightweight `k3s` cluster if you want to get fancy) runs the full stack on a home server.
- Run as a systemd service or via Docker restart policies for 24/7 uptime.
- Add basic auth / local-network-only binding — don't expose the orchestrator to the public internet without a reverse proxy + real auth (see §8 security).

---

## 6. Prompt Engineering

### Core system prompt skeleton (Phase 1+)
```
You are [NAME], a personal AI assistant. Voice-first: keep responses concise
(1-3 sentences) unless the user asks for detail or you're presenting a list/data.
Never use markdown formatting in voice responses — you will be read aloud.
If you don't know something current, use the web_search tool rather than guessing.
If a request requires a tool you have, use it — don't ask permission for
read-only/reversible actions. For irreversible or physical actions, confirm first.

Relevant long-term memory about the user:
{retrieved_memory}

Recent conversation:
{short_term_buffer}
```

### Key prompt-engineering practices to bake in
- **Separate "voice mode" from "text mode" formatting instructions** — Jarvis should never speak markdown bullet points aloud, but a text/web client can render them.
- **Tool-use few-shot examples** in the system prompt for your 3-5 most common tools dramatically improves correct tool selection versus relying on schema alone.
- **Explicit response-length discipline** — this is the single biggest thing that makes an assistant feel "natural" vs "robotic AI assistant-y." Cap default responses hard.
- **Memory injection budget**: cap retrieved long-term memory to ~3-5 facts max per turn — over-injection causes the model to over-reference irrelevant history.
- **Version your prompts** in the repo (`config/prompts/v1_system.md`, `config/prompts/v1/tools/web_search.md`) and log which prompt version produced which response — you will iterate on this constantly and need to A/B compare. The prompt version is included in every LLM generation request's correlation metadata.

---

## 7. CI/CD Pipeline

```yaml
# .github/workflows/ci.yml (conceptual)
on: [push, pull_request]
jobs:
  lint-and-test:
    - ruff/black for Python lint+format
    - pytest for unit tests (mock LLM/STT/TTS calls — never hit real models in CI)
    - mypy for type checking
  build:
    - docker build each service, tag with commit SHA
    - push to GHCR (GitHub Container Registry, free for personal use)
  deploy (optional, self-hosted runner or Watchtower):
    - on merge to main, either:
      (a) self-hosted GitHub Actions runner on your home server pulls + restarts, or
      (b) Watchtower container auto-updates when new images land in GHCR
```

- Keep all model weights **out of the repo and out of CI** — pull them at container-start via Ollama's model pull / Hugging Face download, cached in a Docker volume.
- Integration tests: a small "golden set" of 20-30 text prompts with expected tool-call patterns, run against a cheap local model in CI to catch prompt-regression bugs before they hit your live assistant.

### 7.1 Audio Testing Strategy

Because audio pipelines are notoriously hard to test (they involve hardware, real-time constraints, and non-deterministic latency), build a testable audio abstraction from Phase 0.5 onward:

- **AudioSource abstraction** (`shared/src/shared/audio.py`): an interface that yields audio bytes. `MicrophoneAudioSource` captures from hardware; `FileAudioSource` reads from a WAV file for deterministic testing.
- **AudioSink abstraction**: an interface that consumes audio bytes. `SpeakerAudioSink` plays to hardware; `NullAudioSink` discards bytes (useful for benchmarking without a speaker) and optionally counts them for throughput measurement.
- **Test fixtures**: 3-5 short WAV files (1-5 seconds) with known transcriptions, stored in `tests/fixtures/`. These cover:
  - Clean speech at 16kHz mono (standard Whisper input)
  - Speech with background noise (tests VAD edge cases)
  - Silence (tests VAD timeout behavior)
  - Short utterance (<1s, tests endpointing)
- **CI audio tests** use `FileAudioSource` and `NullAudioSink` exclusively — no hardware dependency. Mark hardware-dependent tests with `@pytest.mark.audio_hardware` and skip them in CI.

### 7.2 Health Checks in CI

Every service's `GET /health` endpoint is tested in CI by starting the service (with mocked dependencies) and verifying the health response. Docker Compose health checks (`healthcheck:` blocks) use these endpoints to manage container lifecycle.

---

## 8. Security & Privacy

- Bind all services to `localhost`/LAN only by default — no port should be internet-facing without a reverse proxy + auth in front of it.
- **ChromaDB encryption**: always encrypt the long-term memory store at rest. Use LUKS for the volume/filesystem layer or `cryptography.fernet` for application-level encryption of stored embeddings and metadata. This is not optional — personal conversations are sensitive data.
- **API key management**: all provider keys (Groq, Gemini, OpenAI, ElevenLabs) are loaded from `.env` and validated by Pydantic Settings at startup. If a required key is missing, the application fails immediately with a clear error message — no silent fallback to a broken state.
- **Redis password protection**: set `requirepass` in redis.conf and pass the password via environment variable to all services that connect to Redis. Never expose Redis to the network without authentication.
- **Rate limiting middleware** on all FastAPI routes from Phase 0 (configurable in `settings.yaml`). This prevents abuse from within the local network and catches runaway loops during development.
- **WebSocket authentication**: from Phase 2 onward, all WebSocket connections require a session token or API key passed in the connection request header. Without it, the connection is rejected at the HTTP upgrade stage.
- **Tool execution sandboxing**: all tool arguments are validated against Pydantic schemas before execution (rejects type mismatches and injection attempts). File I/O tools restrict path resolution to a sandboxed directory — `read_file("../../../etc/passwd")` is rejected, not resolved.
- **Tool safety tiers** (defined in `services/tools/src/tools/registry.py`):
  - **Safe** (auto-execute): read-only tools like `get_datetime`, `web_search`, `read_file`. The LLM can call these freely.
  - **Confirm** (must speak "Shall I proceed?" before execution): tools with side effects like `send_email`, `write_file`, `delete_file`. The orchestrator pauses in SPEAKING state, asks for confirmation, and only executes if the user says yes.
  - **Restricted** (must be in allowlist, no exceptions): high-risk tools like `execute_command`, `modify_system`, `control_hardware`. Only tools in the user-configured allowlist in `settings.yaml` can be called, regardless of what the LLM requests.
- Any tool with real-world side effects (email, smart home, robotics) should log every invocation with timestamp + arguments for auditability.
- If you eventually expose remote access (e.g., talk to Jarvis from your phone away from home), put it behind a VPN (Tailscale is free for personal use) rather than opening ports.

---

## 9. What the Free Stack *Can* Achieve

Built end-to-end as above, you get: a locally-running, privacy-preserving voice assistant with sub-2s response latency, real memory, real tool use (web search, files, APIs), and eventually robotics control — genuinely comparable to early Jarvis-movie functionality, running entirely on hardware you own, at $0 recurring cost (aside from electricity).

---

## 10. Vision: Where the Free Stack Hits a Ceiling (Paid Upgrade Path)

This is the honest part. A few structural limits in the free stack cannot be engineered around — they're bounded by hardware physics or model quality gaps. Here's exactly where paying unlocks real capability, ranked by impact:

### 10.1 Voice-to-voice latency & naturalness — **highest impact**
- **Limitation**: Local Whisper + Ollama + Piper, even well-optimized, tops out around 1-2s round trip on consumer hardware, and Piper's voice, while fast, sounds noticeably synthetic compared to state-of-the-art.
- **Upgrade**: **OpenAI Realtime API** or **ElevenLabs Conversational AI** — these do true speech-to-speech in a single model pass (no separate STT->LLM->TTS chain), achieving ~300-500ms latency with genuinely human-sounding, emotionally inflected voice, including natural interruption handling built in.
- **Cost**: OpenAI Realtime ~$0.06-0.24/min of audio depending on model; ElevenLabs Conversational AI has a paid tier starting ~$5-22+/mo plus usage. For a personal assistant used a few hours a week, this is realistically $10-40/month.
- **This is the single upgrade that makes it *feel* like Jarvis** rather than "a voice assistant I built."

### 10.2 Reasoning quality / model intelligence
- **Limitation**: Even good local 8-14B models (or free-tier cloud models) are noticeably weaker than frontier models at multi-step reasoning, nuanced instruction-following, and complex tool-orchestration — you'll notice this most in Phase 6 agentic planning.
- **Upgrade**: **Claude or GPT-4-class API access** as the reasoning engine (keep local models as a fast/cheap fallback for simple queries — a "router" that sends easy requests local and hard requests to the frontier model is the efficient hybrid pattern).
- **Cost**: Usage-based, typically $5-50/month for personal-scale use depending on query volume and context size.

### 10.3 Vector memory at scale
- **Limitation**: ChromaDB embedded mode is great up to tens of thousands of memory entries; beyond that (years of daily use, large file corpora) query latency and reliability degrade, and it doesn't handle concurrent multi-device access well.
- **Upgrade**: **Pinecone** or **Weaviate Cloud** — managed, scalable vector search with better filtering, hybrid search, and multi-client access.
- **Cost**: Free tiers exist and cover most personal use for a long time; paid tiers start ~$25-70/month only once you're at real scale.

### 10.4 Wake word / far-field audio quality
- **Limitation**: Open-source wake word + a single USB mic performs poorly in noisy rooms or when you're across the room, unlike Alexa/Google Home-grade far-field mic arrays with beamforming and noise cancellation.
- **Upgrade**: **Picovoice Porcupine paid tier** (custom-trained wake word, better accuracy) + a proper **far-field mic array** (e.g., ReSpeaker 4-Mic/6-Mic array, $30-80 one-time hardware cost, not really "paid software" but worth flagging as a physical constraint).
- **Cost**: Mostly one-time hardware (~$50-100), Porcupine custom wake word training ~$0-50/mo depending on tier.

### 10.5 Robotics-grade compute at the edge
- **Limitation**: A Raspberry Pi can run a ROS2 bridge and simple sensor/actuator logic fine, but any on-device vision or real-time control (e.g., object detection for a robot arm, SLAM for navigation) needs real GPU compute that a Pi doesn't have.
- **Upgrade**: **NVIDIA Jetson Orin Nano/NX** ($250-600 one-time) for on-robot AI inference, or route vision/control workloads to your home GPU server / a cloud GPU instance (e.g., **Lambda/RunPod on-demand GPU**, ~$0.20-1/hr) when needed rather than running 24/7.
- **Cost**: Mostly one-time hardware, or cheap on-demand cloud GPU for occasional heavy workloads.

### 10.6 Reliability, observability, and multi-device sync at "real product" polish
- **Limitation**: Free stack has no built-in monitoring, alerting, or multi-device state sync — if a container crashes at 2am, you won't know until you talk to a silent assistant.
- **Upgrade**: Lightweight paid observability (**Grafana Cloud free tier is generous and often enough**, but Datadog/Better Stack if you want more) + a proper sync backend (e.g., **Supabase** paid tier) if you want the assistant's memory/state synced across a phone app, desktop, and home hub simultaneously.
- **Cost**: Often free-tier-sufficient; paid tiers only needed at real multi-user/multi-device scale, ~$10-30/month.

### Summary: recommended first upgrade if/when you're ready to pay
If you only ever pay for **one** thing, make it **§10.1 (Realtime speech-to-speech API)**. It has the single largest effect on whether the assistant *feels* like Jarvis versus feels like a demo, and it's the one gap that local open-source tooling is furthest from closing. Everything else in the free stack gets you 80-90% of the way; voice naturalness and latency is the 10-20% that's hardest to DIY.

---

## 11. Suggested First Sprint (concrete next action)

1. Set up the Phase 0 repo skeleton with Docker Compose.
2. Add the `shared/` package with typed message protocol (Pydantic models for all message types).
3. Build and test the AudioSource/AudioSink abstractions (Phase 0.5) with mock and WAV fixtures.
4. Get Ollama running locally with Qwen2.5-8B or Llama-3.1-8B.
5. Build the Phase 1 CLI text chat loop with streaming responses.
6. Only once that feels solid, move to Phase 2 (turn-based voice).

Happy to generate the actual starter repo (Docker Compose file, FastAPI orchestrator skeleton, and Phase-1 chat loop code) as a next step whenever you're ready to start writing code.
