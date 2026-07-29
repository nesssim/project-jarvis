# J.A.R.V.I.S. — Test Specification Document

> **Version:** 1.0  
> **Based on blueprint:** `jarvis_blueprint.md` (485 lines)  
> **Testing framework:** pytest 8+ with pytest-asyncio, pytest-cov, pytest-mock  
> **E2E framework:** Playwright (for web UI phases)  
> **Target coverage:** ≥80% branches, functions, lines, statements per service

---

## Table of Contents

1. [Testing Philosophy](#1-testing-philosophy)
2. [Test Directory Structure](#2-test-directory-structure)
3. [Phase 0 — Skeleton](#3-phase-0--skeleton)
4. [Phase 0.5 — Audio Primitives](#4-phase-05--audio-primitives)
5. [Phase 1 — Text Brain](#5-phase-1--text-brain)
6. [Phase 2 — Voice I/O Turn-Based](#6-phase-2--voice-io-turn-based)
7. [Phase 2.5 — Streaming Without Barge-In](#7-phase-25--streaming-without-barge-in)
8. [Phase 3 — Real-Time Streaming](#8-phase-3--real-time-streaming)
9. [Phase 4 — Memory](#9-phase-4--memory)
10. [Phase 5 — Tool Calling](#10-phase-5--tool-calling)
11. [Phase 6 — Agentic + Robotics](#11-phase-6--agentic--robotics)
12. [Phase 7 — Deployment](#12-phase-7--deployment)
13. [Running Tests](#13-running-tests)
14. [CI Integration](#14-ci-integration)
15. [Test Fixtures Catalog](#15-test-fixtures-catalog)
16. [TDD Workflow Guidelines](#16-tdd-workflow-guidelines)
17. [Appendices](#17-appendices)

---

## 1. Testing Philosophy

### 1.1 Core Principles

| Principle | Application |
|---|---|
| **Mock external AI models** | Never hit real Ollama, Whisper, Piper, Groq, or Gemini in CI. Mock all LLM/STT/TTS calls at the HTTP/client boundary. |
| **Test audio with fixtures, not hardware** | Use `FileAudioSource` and `NullAudioSink` for deterministic audio tests. Mark hardware-dependent tests with `@pytest.mark.audio_hardware` and skip in CI. |
| **Test state machines exhaustively** | The Phase 3 orchestrator state machine (7 states, 10+ transitions) must be tested via a transition matrix — every valid and invalid transition verified. |
| **Message protocol first** | The shared message protocol (16 message types, envelope) is the backbone of the system. Test serialization/deserialization exhaustively before any service tests. |
| **Vertical slice testing** | Each phase produces a working end-to-end flow. Tests must validate the full slice, not just individual components in isolation. |
| **Latency regression tests** | Critical paths have performance assertions (e.g., state machine transitions must complete under N ms, TTS chunk processing under N ms). |
| **Determinism** | All tests must be reproducible. Use seeded RNG, fixed timestamps, and deterministic fixture content. Never depend on wall-clock timing for correctness. |

### 1.2 Test Types per Phase

| Phase | Unit | Integration | E2E | Performance |
|---|---|---|---|---|
| 0 — Skeleton | ★★★ | ★★★ | — | — |
| 0.5 — Audio | ★★★ | ★★ | — | ★ |
| 1 — Text Brain | ★★★ | ★★★ | ★ | ★ |
| 2 — Voice Turn-Based | ★★★ | ★★★ | ★★ | ★ |
| 2.5 — Streaming | ★★★ | ★★★ | ★★★ | ★★ |
| 3 — Real-Time | ★★★ | ★★★ | ★★★ | ★★★ |
| 4 — Memory | ★★★ | ★★★ | ★★ | ★★ |
| 5 — Tool Calling | ★★★ | ★★★ | ★★ | ★ |
| 6 — Agentic + Robotics | ★★★ | ★★★ | — | ★ |
| 7 — Deployment | ★ | ★★ | ★★★ | ★★ |

★ = some coverage  ★★ = good coverage  ★★★ = exhaustive coverage

### 1.3 Test Doubles Strategy

| External Dependency | Test Double | When to Mock | Notes |
|---|---|---|---|
| **LLM (Ollama/Groq/Gemini)** | `AsyncMock` returning streaming tokens | All unit/integration tests | Use fixture transcripts to simulate streaming responses |
| **STT (Whisper)** | `AsyncMock` returning transcript from WAV fixture | All tests except manual audio-hw tests | Map WAV fixtures to known transcripts |
| **TTS (Piper/Kokoro)** | `AsyncMock` yielding known audio chunks | All tests except manual audio-hw tests | Use 200ms silent WAV chunks as mock output |
| **VAD (Silero)** | Mock returning speech/no-speech booleans | Phase 2.5+ tests | Simulate endpoint patterns |
| **Wake word** | Mock returning detected/not-detected | Phase 3+ tests | Simulate activation patterns |
| **Redis** | `fakeredis` (in-memory Redis mock) | All integration tests | Supports streams, consumer groups, pub/sub |
| **ChromaDB** | In-memory ChromaDB instance | Phase 4 tests | ChromaDB supports ephemeral mode natively |
| **Audio hardware** | `FileAudioSource` / `NullAudioSink` | All automated tests | Hardware tests manual-only |
| **HTTP clients** | `httpx.AsyncClient` with mocked transport | All service tests | Mock external API calls |
| **ROS2** | Mock subscriber/publisher | Phase 6 tests | No ROS2 dependency in CI |
| **WebSocket** | `websockets` test client | Phase 2.5+ tests | FastAPI TestClient supports WS natively |

---

## 2. Test Directory Structure

The test tree mirrors the monorepo layout exactly:

```
tests/
├── conftest.py                          # Root fixtures, pytest plugins, markers
├── pytest.ini                           # pytest configuration
├── fixtures/                            # Shared test data
│   ├── audio/
│   │   ├── speech_clean_16khz.wav       # Clean speech at 16kHz mono
│   │   ├── speech_clean_44khz.wav       # Clean speech at 44.1kHz
│   │   ├── speech_noisy_16khz.wav       # Speech with background noise
│   │   ├── silence_1s_16khz.wav         # 1 second of silence at 16kHz
│   │   └── utterance_short_16khz.wav    # <1s short utterance at 16kHz
│   ├── transcripts/
│   │   ├── known_transcripts.json       # Mapping: WAV file → known transcript
│   │   ├── conversation_3_turns.json    # 3-turn conversation for LLM tests
│   │   └── conversation_10_turns.json   # 10-turn for memory / context tests
│   ├── memory/
│   │   ├── facts.json                   # Known facts for memory retrieval tests
│   │   └── embeddings.json              # Pre-computed embeddings for ChromaDB tests
│   ├── tools/
│   │   ├── weather_response.json        # Mock weather API response
│   │   └── search_results.json          # Mock web search results
│   └── messages/
│       ├── valid_messages.json          # All 16 message types with valid payloads
│       └── invalid_messages.json        # Edge case messages for validation tests
│
├── shared/                              # Tests for shared/ package
│   ├── test_messages.py                 # Message protocol (16 types, serialization, validation)
│   ├── test_config.py                   # Settings loading, validation, overrides
│   ├── test_state.py                    # State machine (IDLE, LISTENING, etc.)
│   ├── test_audio.py                    # AudioSource/Sink abstractions
│   └── test_logging.py                  # Structured logging config
│
├── services/
│   ├── orchestrator/
│   │   ├── test_main.py                 # FastAPI app creation, lifespan, shutdown
│   │   ├── test_health.py               # GET /health endpoint
│   │   ├── test_rate_limiting.py         # Rate limiting middleware
│   │   ├── test_chat_endpoint.py         # POST /chat, streaming SSE/WS
│   │   ├── test_ws_endpoint.py          # WebSocket session lifecycle
│   │   ├── core/
│   │   │   ├── test_state_machine.py     # Formal state machine transitions
│   │   │   ├── test_pipeline.py          # Audio→STT→LLM→TTS orchestration pipeline
│   │   │   └── test_prompt.py            # Prompt assembly, memory injection, truncation
│   │   └── clients/
│   │       ├── test_llm_client.py         # LLM client (Ollama/Groq/Gemini abstraction)
│   │       ├── test_memory_client.py      # Memory service client
│   │       └── test_tools_client.py       # Tool registry client
│   │
│   ├── stt/
│   │   ├── test_main.py                 # STT service app, health, Redis consumer
│   │   ├── test_whisper_stt.py           # faster-whisper wrapper
│   │   └── test_vad.py                  # Silero VAD integration
│   │
│   ├── tts/
│   │   ├── test_main.py                 # TTS service app, health, Redis consumer
│   │   ├── test_piper_tts.py             # Piper TTS wrapper
│   │   └── test_kokoro_tts.py            # Kokoro TTS wrapper
│   │
│   ├── memory/
│   │   ├── test_main.py                 # Memory service app, health, Redis consumer
│   │   ├── test_short_term.py            # Sliding window buffer
│   │   ├── test_long_term.py             # ChromaDB integration
│   │   └── test_extraction.py            # Memory extraction (what to remember)
│   │
│   └── tools/
│       ├── test_main.py                 # Tools service app, health, Redis consumer
│       ├── test_registry.py              # Tool registry pattern, safety tiers
│       ├── test_web_search.py            # Web search tool
│       ├── test_file_io.py               # File I/O tools (sandboxing)
│       └── test_safety_tiers.py          # Confirm/restricted tool execution
│
├── e2e/
│   ├── test_cli_chat.py                 # CLI chat E2E (Phase 1)
│   ├── test_voice_turn_based.py         # Turn-based voice E2E (Phase 2)
│   ├── test_streaming_no_bargein.py     # Streaming without barge-in E2E (Phase 2.5)
│   ├── test_realtime_conversation.py    # Real-time streaming E2E (Phase 3)
│   └── test_tool_calling.py             # Tool calling E2E (Phase 5)
│
├── performance/
│   ├── test_latency_budget.py           # End-to-end latency assertions
│   ├── test_audio_throughput.py         # Audio chunk processing throughput
│   └── test_memory_query_latency.py     # Memory retrieval < 100ms assertion
│
└── conftest_phases/
    ├── conftest_phase0.py               # Phase 0 fixtures (Docker Compose, Redis mock)
    ├── conftest_audio.py                # Phase 0.5 fixtures (WAV files, audio sources)
    ├── conftest_llm.py                  # Phase 1 fixtures (mock LLM responses)
    ├── conftest_streaming.py            # Phase 2.5+ fixtures (WebSocket clients, stream mocks)
    ├── conftest_memory.py               # Phase 4 fixtures (ChromaDB in-memory, facts)
    └── conftest_tools.py                # Phase 5 fixtures (tool registry, mock responses)
```

### `pytest.ini`

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
markers =
    audio_hardware: Tests that require real microphone/speaker hardware
    slow: Tests that take >5 seconds
    performance: Performance/latency regression tests
    e2e: End-to-end tests
    smoke: Fast smoke tests for CI pre-merge
    unit: Pure unit tests (no external dependencies)
    integration: Tests that touch databases/external services (mocked)
    flaky: Known flaky tests that need investigation
filterwarnings =
    ignore::DeprecationWarning
    ignore::pytest.PytestUnknownMarkWarning
log_cli = true
log_cli_level = INFO
```

---

## 3. Phase 0 — Skeleton

> **Goal:** Repo & infra skeleton — Git, Docker, config system, logging, health checks.
> **Implementation tasks:** [Phase 0 in schedule.md](./schedule.md#phase-0--skeleton)

### 3.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `shared/src/shared/messages.py` | `shared/test_messages.py` | — All 16 message types serialize/deserialize round-trip<br>— Envelope fields (`request_id`, `timestamp`, `type`, `payload`) are validated<br>— Invalid message types raise `ValueError`<br>— Missing required fields raise `ValidationError`<br>— Extra fields are rejected (Pydantic strict mode)<br>— `TRANSCRIPT_PARTIAL` accepts partial text<br>— `LLM_TOOL_CALL` payload validates tool schema<br>— `MEMORY_RETRIEVE_RESULT` payload validates fact list<br>— Timestamps must be positive floats<br>— `request_id` must be non-empty string |
| `shared/src/shared/config.py` | `shared/test_config.py` | — Settings load from YAML + env overrides<br>— Missing required keys raise clear error<br>— Provider keys validated as non-empty strings<br>— Rate limit config parsed correctly<br>— Graceful shutdown timeout parsed<br>— `settings.yaml` schema matches `settings.schema.json` |
| `shared/src/shared/logging.py` | `shared/test_logging.py` | — structlog configured to output JSON<br>— Log level configurable via env<br>— Sensitive fields redacted (API keys)<br>— Correlation ID injected into log context |
| `shared/src/shared/state.py` | `shared/test_state.py` | — Phase 0 basic health state enum<br>— State transitions validated<br>— String representation for logging |
| `services/orchestrator/src/main.py` | `services/orchestrator/test_main.py` | — FastAPI app created with correct lifespan<br>— Startup initializes Redis client<br>— Shutdown closes connections gracefully<br>— Lifespan handles startup failure (e.g., Redis unreachable) |

### 3.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| `services/orchestrator/test_health.py` | — `GET /health` returns `{"status": "ok", "dependencies": {"redis": true}}`<br>— Health endpoint returns 503 when Redis is down<br>— Response time < 50ms |
| `services/orchestrator/test_rate_limiting.py` | — Default rate limit applied<br>— Per-endpoint overrides work<br>— Rate limit exceeded returns 429 with `Retry-After` header<br>— Rate limit resets correctly |

### 3.3 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **Redis** | `fakeredis.aioredis.FakeRedis()` | In-memory, supports Streams, consumer groups, pub/sub. Import in `conftest.py` and inject via dependency override. |
| **Settings** | `pytest.mark.parametrize` with `Settings(...model_config=...)` | Override env vars per test case. |

### 3.4 Coverage Requirements

| Module | Target |
|---|---|
| `shared/src/shared/messages.py` | 100% branches, lines, statements |
| `shared/src/shared/config.py` | 95% branches, lines |
| `shared/src/shared/logging.py` | 90% lines |
| `services/orchestrator/src/main.py` (lifespan) | 90% branches |

### 3.5 Test Fixtures Needed

| Fixture | File | Description |
|---|---|---|
| `mock_redis` | `conftest.py` (root) | `fakeredis.aioredis.FakeRedis()` instance, shared across tests |
| `settings_override` | `conftest.py` | Pytest fixture to temporarily override settings |
| `health_response_schema` | — | JSON Schema for health endpoint response validation |

### 3.6 Done Criteria (Test-Specific)

- [ ] All 16 message types have round-trip serialization tests passing
- [ ] Invalid message types and payloads are rejected with appropriate exceptions
- [ ] `GET /health` returns correct status with mocked dependencies up and down
- [ ] Rate limiting middleware correctly limits and resets
- [ ] Graceful shutdown sequence tested (SIGTERM → complete in-flight → ack messages → exit)
- [ ] All tests pass without any external dependency (Redis mocked via fakeredis)

### 3.7 Key Test Patterns for Phase 0

```python
# Example: Message protocol exhaustive test
import pytest
from pydantic import ValidationError
from shared.messages import (
    Message, MessageType, TranscriptMessage, VADMessage,
    TTSMessage, LLMMessage, MemoryMessage,
)

# Generate parametrized tests for all 16 message types
MESSAGE_TYPES = [
    (MessageType.TRANSCRIPT_PARTIAL, {"text": "hello", "language": "en"}),
    (MessageType.TRANSCRIPT_FINAL, {"text": "hello world", "language": "en", "confidence": 0.95}),
    (MessageType.VAD_SPEECH_START, {}),
    (MessageType.VAD_SPEECH_END, {"duration_ms": 1200}),
    (MessageType.TTS_SYNTHESIZE, {"text": "Hello there", "voice": "default"}),
    (MessageType.TTS_STOP, {}),
    (MessageType.TTS_AUDIO_CHUNK, {"audio": "base64encodedbytes", "sequence": 1, "is_final": False}),
    (MessageType.TTS_COMPLETE, {"total_chunks": 15, "duration_ms": 3200}),
    (MessageType.LLM_GENERATE, {"prompt": "Hello", "max_tokens": 256}),
    (MessageType.LLM_CANCEL, {"reason": "barge_in"}),
    (MessageType.LLM_TOKEN, {"token": "Hello", "index": 0}),
    (MessageType.LLM_COMPLETE, {"finish_reason": "stop", "total_tokens": 42}),
    (MessageType.LLM_TOOL_CALL, {"tool": "web_search", "arguments": {"query": "weather"}}),
    (MessageType.MEMORY_STORE, {"facts": [{"text": "User likes coffee", "importance": 0.8}]}),
    (MessageType.MEMORY_RETRIEVE, {"query": "What do I like?", "top_k": 5}),
    (MessageType.MEMORY_RETRIEVE_RESULT, {"facts": [], "query": "What do I like?"}),
]

@pytest.mark.parametrize("msg_type,payload", MESSAGE_TYPES)
def test_message_type_roundtrip(msg_type, payload):
    """All 16 message types serialize and deserialize correctly."""
    msg = Message(type=msg_type, payload=payload, request_id="test-1", timestamp=1000.0)
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored == msg
    assert restored.type == msg_type
    assert restored.request_id == "test-1"


def test_message_rejects_missing_request_id():
    """request_id is required and must be non-empty."""
    with pytest.raises(ValidationError):
        Message(type=MessageType.TRANSCRIPT_FINAL, payload={}, request_id="", timestamp=1000.0)

    with pytest.raises(ValidationError):
        Message(type=MessageType.TRANSCRIPT_FINAL, payload={}, timestamp=1000.0)


def test_message_rejects_invalid_type():
    """Unknown message types are rejected at validation."""
    with pytest.raises(ValidationError):
        Message(type="INVALID_TYPE", payload={}, request_id="test-1", timestamp=1000.0)


def test_message_rejects_extra_fields():
    """Extra fields in the envelope are rejected (strict mode)."""
    with pytest.raises(ValidationError):
        Message.model_validate({
            "type": "TRANSCRIPT_FINAL",
            "payload": {"text": "hello"},
            "request_id": "test-1",
            "timestamp": 1000.0,
            "extra_field": "should_not_exist"
        })


# --- Config tests ---

def test_config_validates_required_keys():
    """Missing required provider keys raise clear error."""
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(providers={"openai": {"api_key": ""}})


def test_config_loads_from_yaml(tmp_path):
    """Settings correctly parse a minimal YAML config."""
    yaml_content = """
    providers:
      ollama:
        base_url: "http://localhost:11434"
        model: "qwen2.5-8b"
    rate_limiting:
      default: 100
    """
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml_content)
    settings = Settings.from_yaml(config_file)
    assert settings.providers.ollama.base_url == "http://localhost:11434"
    assert settings.rate_limiting.default == 100
```

---

## 4. Phase 0.5 — Audio Primitives

> **Goal:** AudioSource/AudioSink abstractions, WAV test fixtures.
> **Implementation tasks:** [Phase 0.5 in schedule.md](./schedule.md#phase-05--audio-primitives)

### 4.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `shared/src/shared/audio.py` — `AudioSource` | `shared/test_audio.py` | — `AudioSource` is abstract (cannot instantiate)<br>— `MicrophoneAudioSource` returns bytes from hardware (manual only)<br>— `FileAudioSource` reads complete WAV file contents<br>— `FileAudioSource.read()` yields correct byte count<br>— `FileAudioSource` handles missing file with `FileNotFoundError`<br>— `FileAudioSource` handles empty WAV file<br>— `FileAudioSource` can read 16kHz and 44.1kHz WAVs<br>— `FileAudioSource` reports correct sample rate and channels<br>— `FileAudioSource` handles seek/reset for replay |
| `shared/src/shared/audio.py` — `AudioSink` | `shared/test_audio.py` | — `AudioSink` is abstract<br>— `SpeakerAudioSink` plays to hardware (manual only)<br>— `NullAudioSink.write()` accepts bytes and discards them<br>— `NullAudioSink.write()` counts total bytes written<br>— `NullAudioSink` can measure throughput (bytes/sec)<br>— `NullAudioSink` handles empty bytes gracefully<br>— `NullAudioSink` handles large chunks (10MB+) without memory issues |
| WAV parsing helpers | `shared/test_audio.py` | — Correctly parse WAV header (sample rate, bit depth, channels)<br>— Reject invalid WAV headers<br>— Handle WAV with metadata chunks |

### 4.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| `FileAudioSource` → `NullAudioSink` pipeline | — Bytes read from WAV fixture flow correctly through the sink<br>— Byte count matches expected (file size - header)<br>— Multiple sequential reads produce consistent results |

### 4.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `@pytest.mark.audio_hardware` — Mic → File record | — `MicrophoneAudioSource` captures N seconds and produces non-zero bytes (manual, skipped in CI) |
| `@pytest.mark.audio_hardware` — File → Speaker | — `SpeakerAudioSink` plays a known WAV without error (manual, skipped in CI) |

### 4.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **Sounddevice** | `unittest.mock.patch('sounddevice.InputStream')` | Mock for `MicrophoneAudioSource` tests that avoid hardware |
| **WAV files** | `tests/fixtures/audio/*.wav` | Real WAV fixtures for `FileAudioSource` tests |

### 4.5 Coverage Requirements

| Module | Target |
|---|---|
| `shared/src/shared/audio.py` — AudioSource | 95% branches |
| `shared/src/shared/audio.py` — AudioSink | 95% branches |
| WAV parsing utilities | 100% lines |

### 4.6 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `clean_speech_16khz` | 3-second WAV: "Hello, this is a test utterance for the voice assistant." 16kHz mono 16-bit PCM |
| `clean_speech_44khz` | Same utterance at 44.1kHz to test sample rate handling |
| `noisy_speech_16khz` | Speech with cafe background noise (tests VAD resilience) |
| `silence_1s` | 1 second of silence at 16kHz (tests VAD timeout) |
| `short_utterance_16khz` | 0.8s: "Yes." (tests endpointing with very short speech) |
| `expected_bytes_by_file` | Dict mapping fixture name → (byte_count_min, byte_count_max, transcript, sample_rate) |

### 4.7 Done Criteria (Test-Specific)

- [ ] `FileAudioSource` reads all 5 WAV fixtures with correct byte counts
- [ ] `NullAudioSink` correctly discards and counts bytes for all fixtures
- [ ] Pipeline test passes: `FileAudioSource → NullAudioSink` byte count matches expected
- [ ] Invalid WAV files are rejected with clear error messages
- [ ] All tests pass without audio hardware (using FileAudioSource + NullAudioSink)
- [ ] `pytest tests/ --audio-hardware` flag exists for manual hardware verification

### 4.8 Key Test Patterns for Phase 0.5

```python
import pytest
import numpy as np
from pathlib import Path
from shared.audio import FileAudioSource, NullAudioSink, InvalidWAVError


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture
def clean_speech_source():
    return FileAudioSource(str(FIXTURE_DIR / "speech_clean_16khz.wav"))


class TestFileAudioSource:
    """FileAudioSource deterministic tests (no hardware needed)."""

    def test_reads_complete_file(self, clean_speech_source):
        """Reading all chunks yields total bytes equal to PCM data size."""
        all_bytes = b"".join(clean_speech_source.read(chunk_size=4096))
        expected_size = clean_speech_source.pcm_data_size
        assert len(all_bytes) == expected_size

    def test_chunk_size_respected(self, clean_speech_source):
        """Individual chunks do not exceed requested chunk_size."""
        for chunk in clean_speech_source.read(chunk_size=1024):
            assert len(chunk) <= 1024

    def test_reports_correct_properties(self, clean_speech_source):
        """Sample rate, channels, and bit depth are parsed from WAV header."""
        assert clean_speech_source.sample_rate == 16000
        assert clean_speech_source.channels == 1
        assert clean_speech_source.bit_depth == 16

    def test_reset_allows_reread(self, clean_speech_source):
        """After reset(), the source can be read again from the beginning."""
        first_read = b"".join(clean_speech_source.read(chunk_size=4096))
        clean_speech_source.reset()
        second_read = b"".join(clean_speech_source.read(chunk_size=4096))
        assert first_read == second_read

    def test_missing_file_raises(self):
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            FileAudioSource("/nonexistent/file.wav")

    def test_invalid_wav_rejected(self, tmp_path):
        """File with garbage content raises InvalidWAVError."""
        bad_file = tmp_path / "not_a_wav.wav"
        bad_file.write_bytes(b"\x00\x00\x00\x00")
        with pytest.raises(InvalidWAVError):
            FileAudioSource(str(bad_file))

    @pytest.mark.parametrize("fixture_name,expected_rate", [
        ("speech_clean_16khz.wav", 16000),
        ("speech_clean_44khz.wav", 44100),
    ])
    def test_sample_rate_detection(self, fixture_name, expected_rate):
        """Different sample rates are correctly detected."""
        source = FileAudioSource(str(FIXTURE_DIR / fixture_name))
        assert source.sample_rate == expected_rate


class TestNullAudioSink:
    """NullAudioSink discards bytes but measures throughput."""

    def test_discards_bytes(self):
        """Written bytes are discarded (no playback)."""
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)
        # No exception = success for discard behavior

    def test_counts_written_bytes(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)
        sink.write(b"\x00" * 512)
        assert sink.total_bytes_written == 1536

    def test_reports_throughput(self):
        """Throughput measurement returns bytes per second."""
        sink = NullAudioSink()
        import time
        sink.write(b"\x00" * 16000)
        # Throughput should be > 0 (actual value depends on timing)
        assert sink.throughput_bytes_per_sec > 0

    def test_reset_clears_counters(self):
        sink = NullAudioSink()
        sink.write(b"\x00" * 1024)
        sink.reset()
        assert sink.total_bytes_written == 0

    def test_empty_bytes_handled(self):
        """Writing empty bytes is a no-op, not an error."""
        sink = NullAudioSink()
        sink.write(b"")  # Should not raise


@pytest.mark.audio_hardware
class TestMicrophoneAudioSource:
    """Hardware-dependent mic tests (skipped in CI)."""

    def test_captures_nonzero_bytes(self):
        """Microphone capture produces non-zero audio data."""
        source = MicrophoneAudioSource(sample_rate=16000, channels=1)
        chunks = list(source.read(chunk_size=4096, duration_sec=2))
        all_bytes = b"".join(chunks)
        assert len(all_bytes) > 0
        # Ensure not all zeros (silence is possible but rare in 2s)
        assert any(b != 0 for b in all_bytes[:16000])


# --- Pipeline integration test ---

def test_file_source_to_null_sink_pipeline(clean_speech_source):
    """FileAudioSource → NullAudioSink: bytes flow end-to-end."""
    sink = NullAudioSink()
    for chunk in clean_speech_source.read(chunk_size=4096):
        sink.write(chunk)
    assert sink.total_bytes_written == clean_speech_source.pcm_data_size
```

---

## 5. Phase 1 — Text Brain

> **Goal:** LLM client, system prompt, CLI streaming chat.
> **Implementation tasks:** [Phase 1 in schedule.md](./schedule.md#phase-1--text-brain)

### 5.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/orchestrator/src/clients/llm.py` | `orchestrator/clients/test_llm_client.py` | — LLM client abstracts over providers (Ollama, Groq, Gemini)<br>— `generate()` returns async iterable of tokens<br>— Streaming response yields tokens in order<br>— Non-streaming response works<br>— API errors (401, 429, 500) raised as `LLMConnectionError`<br>— Timeout raises `LLMTimeoutError`<br>— Max retries respected with exponential backoff<br>— Empty response handled gracefully<br>— Very long response (>10k tokens) handled without memory blowup |
| `services/orchestrator/src/core/prompt.py` | `orchestrator/core/test_prompt.py` | — System prompt assembled from template + variables<br>— Memory injected correctly into `{retrieved_memory}` slot<br>— Conversation buffer injected into `{short_term_buffer}` slot<br>— Prompt truncation preserves whole turns<br>— Context window limit respected (drop oldest turns)<br>— Prompt version metadata included in correlation data |
| `services/orchestrator/src/routes/chat.py` | `orchestrator/test_chat_endpoint.py` | — SSE endpoint streams tokens<br>— WebSocket endpoint streams tokens<br>— Request validation (empty prompt rejected)<br>— Special characters in input handled (Unicode, emoji, SQLi attempts) |

### 5.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| `/chat` SSE endpoint with mock LLM | — Client receives streamed tokens in correct order<br>— Response headers include content-type and cache-control<br>— Connection close signals end of stream |
| CLI chat loop | — stdin → API → streamed stdout works<br>— Ctrl+C gracefully exits<br>— Empty input handled without error |

### 5.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_cli_chat.py` | — Full CLI interaction with mock LLM: input prompt → see streamed response<br>— Multi-turn conversation context maintained<br>— `exit` command terminates the loop |

### 5.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **Ollama** | `httpx.AsyncClient` mock transport | Intercept `/api/generate` and `/api/chat` calls |
| **Groq** | Mock transport for `https://api.groq.com` | Same approach, different URL pattern |
| **Gemini** | Mock transport for `https://generativelanguage.googleapis.com` | Same approach, different URL pattern |

### 5.5 Coverage Requirements

| Module | Target |
|---|---|
| `clients/llm.py` | 95% branches, 100% error paths |
| `core/prompt.py` | 95% branches, 100% lines |
| `routes/chat.py` | 90% branches |

### 5.6 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `mock_llm_response_stream` | Async generator yielding 5 tokens: ["Hello", " ", "world", ".", ""] |
| `mock_llm_response_complete` | Single string: "Hello world." |
| `mock_llm_error_429` | HTTP 429 response to test retry logic |
| `mock_llm_error_500` | HTTP 500 response for non-retriable error testing |
| `system_prompt_template` | The Phase 1 system prompt with `{retrieved_memory}` and `{short_term_buffer}` slots |
| `conversation_transcript_3_turns` | 3-turn conversation fixture for prompt assembly tests |

### 5.7 Done Criteria (Test-Specific)

- [ ] LLM client works with all 3 provider abstractions (Ollama, Groq, Gemini)
- [ ] Streaming tokens deliver correctly via SSE and WebSocket
- [ ] All error types (auth, rate-limit, timeout, server error) are handled with specific exceptions
- [ ] Prompt template correctly interpolates memory and conversation buffer
- [ ] Context window truncation preserves entire turns (no mid-response cuts)
- [ ] CLI chat loop boots, streams response, and exits cleanly
- [ ] Retry logic with exponential backback works for transient errors

### 5.8 Key Test Patterns for Phase 1

```python
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.clients.llm import LLMClient, LLMConnectionError, LLMTimeoutError
from orchestrator.core.prompt import PromptBuilder


class TestLLMClient:
    """LLM client tests with mocked HTTP transport."""

    @pytest.fixture
    def mock_ollama_stream(self):
        """Simulate Ollama's streaming /api/generate response."""
        async def _stream():
            tokens = ["Hello", " ", "from", " ", "Jarvis", "."]
            for token in tokens:
                yield {"response": token}
        return _stream()

    async def test_streaming_generates_tokens(self, mock_ollama_stream):
        """LLM client yields tokens from streaming response."""
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_stream.return_value.__aenter__.return_value.aiter_bytes = mock_ollama_stream
            client = LLMClient(provider="ollama", base_url="http://localhost:11434")
            tokens = []
            async for token in client.generate("Hello"):
                tokens.append(token)
            assert len(tokens) == 6
            assert "".join(tokens) == "Hello from Jarvis."

    async def test_api_error_raised(self):
        """HTTP 429 raises LLMConnectionError with specific message."""
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_response = AsyncMock()
            mock_response.status_code = 429
            mock_response.text = "Rate limit exceeded"
            mock_stream.return_value.__aenter__.return_value = mock_response

            client = LLMClient(provider="ollama", base_url="http://localhost:11434")
            with pytest.raises(LLMConnectionError, match="429"):
                async for _ in client.generate("Hello"):
                    pass

    async def test_timeout_raises(self):
        """Request timeout raises LLMTimeoutError."""
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_stream.side_effect = httpx.TimeoutException("Connection timed out")
            client = LLMClient(provider="ollama", base_url="http://localhost:11434")
            with pytest.raises(LLMTimeoutError):
                async for _ in client.generate("Hello"):
                    pass

    async def test_empty_response_returns_empty_string(self):
        """Empty LLM response yields empty token list, not error."""
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_stream.return_value.__aenter__.return_value.aiter_bytes = async_gen([])
            client = LLMClient(provider="ollama", base_url="http://localhost:11434")
            tokens = [t async for t in client.generate("Hello")]
            assert tokens == []


class TestPromptBuilder:
    """Prompt assembly and truncation tests."""

    def test_system_prompt_injects_memory(self):
        """System prompt template correctly substitutes memory and conversation."""
        builder = PromptBuilder(template="System: {system}\nMemory: {retrieved_memory}\nConvo: {short_term_buffer}")
        prompt = builder.build(
            system="You are Jarvis.",
            retrieved_memory="User likes coffee.",
            short_term_buffer="User: Hi\nAssistant: Hello."
        )
        assert "You are Jarvis." in prompt
        assert "User likes coffee." in prompt
        assert "User: Hi\nAssistant: Hello." in prompt

    def test_truncation_keeps_whole_turns(self):
        """Truncation drops oldest turn pairs, never mid-response."""
        builder = PromptBuilder(max_context_tokens=50)
        turns = [
            ("User: Question 1", "Assistant: Answer 1"),
            ("User: Question 2", "Assistant: Answer 2"),
            ("User: Question 3", "Assistant: Answer 3"),
        ]
        truncated = builder.truncate_conversation(turns)
        # Should drop oldest turns to fit context window
        for turn in truncated:
            assert turn[0].startswith("User: ")
            assert turn[1].startswith("Assistant: ")
        # Verify no partial turns
        assert len(truncated) <= len(turns)

    def test_special_characters_handled(self):
        """Unicode, emoji, and special characters pass through correctly."""
        builder = PromptBuilder()
        prompt = builder.build(
            system="System",
            retrieved_memory="",
            short_term_buffer="User: Hello 🌍 ¿Cómo estás? SELECT * FROM users;"
        )
        assert "🌍" in prompt
        assert "¿Cómo estás?" in prompt
        assert "SELECT * FROM users;" in prompt
```

---

## 6. Phase 2 — Voice I/O Turn-Based

> **Goal:** STT (Whisper), TTS (Piper/Kokoro), audio I/O, keypress recording.
> **Implementation tasks:** [Phase 2 in schedule.md](./schedule.md#phase-2--voice-io-turn-based)

### 6.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/stt/src/whisper_stt.py` | `stt/test_whisper_stt.py` | — `transcribe()` accepts bytes, returns transcript string<br>— Language detection works<br>— Empty audio returns empty transcript (not error)<br>— Very short audio (<0.1s) handled gracefully<br>— Model loading happens once (lazy singleton)<br>— Model not found raises `STTModelError`<br>— GPU/CPU device selection logic |
| `services/stt/src/vad.py` | `stt/test_vad.py` | — Silero VAD detects speech in audio with speech<br>— Silero VAD returns no-speech for silence fixture<br>— Configurable threshold affects sensitivity<br>— `is_speech()` returns boolean per chunk<br>— VAD state machine: SILENCE → SPEECH → SILENCE<br>— Minimum speech duration filter (remove noise spikes) |
| `services/tts/src/piper_tts.py` | `tts/test_piper_tts.py` | — `synthesize()` returns async iterable of audio chunks<br>— Chunks are valid audio (correct sample rate, bit depth)<br>— Empty text raises `TTSInputError`<br>— Very long text is chunked correctly<br>— Voice configuration applied correctly |
| `services/tts/src/kokoro_tts.py` | `tts/test_kokoro_tts.py` | — Same patterns as Piper tests |
| `services/orchestrator/src/routes/chat.py` (WS) | `orchestrator/test_ws_endpoint.py` | — WebSocket accepts connection with valid session token<br>— WebSocket rejects connection without token<br>— Audio message → STT request → LLM → TTS → audio response flow |

### 6.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| STT service with mocked Whisper | — Redis Stream consumer receives audio bytes → publishes transcript |
| TTS service with mocked Piper | — Redis Stream consumer receives text → publishes audio chunks |
| Orchestrator turn-based flow | — Audio in → STT transcript → LLM response → TTS audio → audio out |

### 6.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_voice_turn_based.py` | — Keypress recording captures audio → receives spoken response<br>— Round-trip time under 4s (with mocked models)<br>— Recorded audio is actually processed (not dropped) |

### 6.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **faster-whisper** | `unittest.mock.patch('faster_whisper.WhisperModel')` | Return transcript from fixture mapping |
| **Silero VAD** | `unittest.mock.patch('silero_vad.load_silero_vad')` | Return speech/no-speech based on fixture |
| **Piper TTS** | Mock subprocess or ctypes call | Return known audio chunks |
| **Kokoro TTS** | Mock HTTP call or local inference | Return known audio chunks |
| **Sounddevice** | `unittest.mock.patch('sounddevice.InputStream')` | Return fixture audio data on read |

### 6.5 Coverage Requirements

| Module | Target |
|---|---|
| `stt/src/whisper_stt.py` | 90% branches, 100% error paths |
| `stt/src/vad.py` | 95% branches, exhaustive state machine coverage |
| `tts/src/piper_tts.py` | 90% branches |
| `tts/src/kokoro_tts.py` | 90% branches |
| WS endpoint auth | 100% branches |

### 6.6 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `mock_whisper_transcript` | Returns known transcript for each WAV fixture |
| `mock_piper_audio_chunks` | List of `(chunk_bytes, is_final)` tuples for Piper output |
| `mock_vad_speech_pattern` | Pre-computed VAD results: `[(timestamp, is_speech), ...]` for each fixture |
| `valid_session_token` | A valid JWT or API key for WebSocket auth tests |
| `invalid_session_token` | Expired/malformed token for auth rejection tests |

### 6.7 Done Criteria (Test-Specific)

- [ ] STT service transcribes all WAV fixtures with accuracy >90% (w.r.t. known transcripts)
- [ ] TTS service synthesizes text to valid audio chunks for all test phrases
- [ ] VAD correctly classifies speech vs silence vs noise for all 5 audio fixtures
- [ ] WebSocket connection secured by session token — rejected without valid token
- [ ] Turn-based round-trip completes: mic → STT → LLM → TTS → speaker
- [ ] Round-trip time with mocked models < 500ms (pipeline overhead, not model inference)

---

## 7. Phase 2.5 — Streaming Without Barge-In

> **Goal:** WebSocket streaming audio, streaming STT partials, streaming LLM, full-utterance TTS.
> **Implementation tasks:** [Phase 2.5 in schedule.md](./schedule.md#phase-25--streaming-without-barge-in)

### 7.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/orchestrator/src/routes/ws.py` | `orchestrator/test_ws_endpoint.py` | — WebSocket accepts continuous binary audio stream<br>— Audio frames forwarded to STT stream<br>— Partial transcripts received and forwarded to client<br>— Full-utterance TTS: waits for complete LLM response before synthesizing |
| `services/orchestrator/src/core/pipeline.py` | `orchestrator/core/test_pipeline.py` | — Streaming pipeline orchestrates STT → LLM → TTS<br>— Partial transcripts emitted to client<br>— No audio overlap (input stops before output starts) |

### 7.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| WebSocket → STT → partials → client | — Continuous audio stream produces partial + final transcripts<br>— Partials have increasing confidence / completeness |
| Streaming LLM → client | — LLM tokens stream to client as they arrive<br>— Client sees streaming text but waits for complete TTS audio |
| Full-utterance TTS pipeline | — TTS waits for complete LLM response<br>— Audio chunks play after LLM finishes |

### 7.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_streaming_no_bargein.py` | — User speaks (no keypress), sees streaming transcription on screen<br>— Receives complete spoken response after LLM finishes<br>— If user speaks during playback, audio is discarded (logged) |

### 7.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **Streaming STT** | AsyncMock yielding partials → final transcript | Simulate Whisper streaming mode |
| **Streaming LLM** | Async generator yielding tokens | Same as Phase 1 |
| **TTS** | Async generator yielding audio chunks | Yield chunks only after `generate()` complete signal |

### 7.5 Coverage Requirements

| Module | Target |
|---|---|
| `routes/ws.py` | 90% branches |
| `core/pipeline.py` (streaming path) | 90% branches |

### 7.6 Done Criteria (Test-Specific)

- [ ] WebSocket streaming audio → STT partials → client text display works
- [ ] LLM tokens stream to display in real-time
- [ ] TTS waits for full response before synthesizing (no sentence-chunking yet)
- [ ] User speech during playback is logged and discarded (no crash)
- [ ] Disconnect during streaming handled gracefully (no orphaned resources)

---

## 8. Phase 3 — Real-Time Streaming

> **Goal:** 7-state FSM, VAD, wake word, sentence-chunked TTS, barge-in. This is the hardest testing phase.
> **Implementation tasks:** [Phase 3 in schedule.md](./schedule.md#phase-3--real-time-streaming)

### 8.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `shared/src/shared/state.py` | `shared/test_state.py` (extended) | — 7 states defined: `IDLE, LISTENING, PROCESSING, SPEAKING, INTERRUPTED, TOOL_WAITING, ERROR` |
| `services/orchestrator/src/core/state_machine.py` | `orchestrator/core/test_state_machine.py` | — **ALL valid transitions tested via transition matrix** (see below)<br>— **ALL invalid transitions raise `InvalidTransitionError`**<br>— LISTENING timeout (default 5s) transitions to IDLE<br>— Barge-in: SPEAKING → INTERRUPTED → LISTENING<br>— TOOL_WAITING: PROCESSING → TOOL_WAITING → PROCESSING<br>— ERROR: ANY → ERROR → IDLE (after recovery)<br>— Event callbacks fire on each transition<br>— Concurrent event handling (barge-in during state transition) |
| `services/orchestrator/src/core/pipeline.py` | `orchestrator/core/test_pipeline.py` | — Sentence-chunked TTS: each complete sentence synthesizes independently<br>— Streaming STT → LLM → TTS with no unnecessary waits<br>— Barge-in: current TTS chunk finishes, then stop<br>— Cold-start strategy (warm-up sequence on boot) |

### 8.2 State Machine Transition Matrix Test

This is the critical testing artifact for Phase 3. The test must verify every valid and invalid transition exhaustively.

```
TEST MATRIX — State Machine Transitions

Current State   →   Event                    →   Next State        Valid?
──────────────────────────────────────────────────────────────────────
IDLE            →   wake_word_detected       →   LISTENING         YES
IDLE            →   vad_speech_start         →   LISTENING         YES
IDLE            →   timeout                  →   ERROR             YES (unusual but valid)
IDLE            →   end_of_speech            →   ERROR             NO
IDLE            →   llm_token                →   ERROR             NO
LISTENING       →   end_of_speech            →   PROCESSING        YES
LISTENING       →   timeout (5s silence)     →   IDLE              YES
LISTENING       →   wake_word_detected       →   LISTENING         YES (re-trigger, reset timer)
LISTENING       →   vad_speech_start         →   LISTENING         YES (already listening)
LISTENING       →   llm_token                →   ERROR             NO
PROCESSING      →   first_sentence_ready     →   SPEAKING          YES
PROCESSING      →   tool_call                →   TOOL_WAITING      YES
PROCESSING      →   vad_speech_start         →   INTERRUPTED       YES (barge-in)
PROCESSING      →   llm_complete             →   SPEAKING          YES (all sentences ready)
PROCESSING      →   wake_word_detected       →   INTERRUPTED       YES
SPEAKING        →   vad_speech_start         →   INTERRUPTED       YES (barge-in)
SPEAKING        →   tts_complete             →   IDLE              YES
SPEAKING        →   wake_word_detected       →   INTERRUPTED       YES
SPEAKING        →   end_of_speech            →   ERROR             NO (already speaking)
INTERRUPTED     →   vad_stop                 →   LISTENING         YES
INTERRUPTED     →   timeout                  →   IDLE              YES
INTERRUPTED     →   end_of_speech            →   LISTENING         YES
TOOL_WAITING    →   tool_result_received     →   PROCESSING        YES
TOOL_WAITING    →   tool_timeout             →   SPEAKING          YES ("tool unavailable")
TOOL_WAITING    →   vad_speech_start         →   INTERRUPTED       YES (barge-in)
TOOL_WAITING    →   wake_word_detected       →   INTERRUPTED       YES
ERROR           →   recovery_success         →   IDLE              YES
ERROR           →   recovery_timeout         →   ERROR             YES (stay in error)
ANY             →   component_failure        →   ERROR             YES
```

### 8.3 Integration Test Targets

| Test | What to Verify |
|---|---|
| Full streaming pipeline: mic stream → VAD → STT (partials) → LLM (streaming) → TTS (sentence-chunked) → speaker | — End-to-end audio flow<br>— Latency meets budget targets<br>— Barge-in correctly interrupts and re-listens |
| STT partial emission timing | — Partials arrive within 150ms of speech end |
| TTS sentence chunking | — Sentences are correctly split and synthesized independently |

### 8.4 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_realtime_conversation.py` | — Full conversational flow: wake → speak → hear response → interrupt → speak again<br>— Multiple barge-in cycles<br>— Long idle timeout → IDLE → re-wake |
| Latency budget check | — End of speech → first STT partial < 150ms<br>— Final transcript → first LLM token < 300ms<br>— Between LLM tokens ~30-50ms/token<br>— First sentence → first TTS byte < 200ms<br>— Total perceived latency < 1.5s |

### 8.5 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **VAD** | Mock returning speech/no-speech at precise timestamps | Use pre-recorded speech patterns from fixtures |
| **Wake word** | Mock returning detected/not-detected | Simulate wake word at specific points in test sequence |
| **STT partials** | Pre-recorded sequence of (partial_text, is_final) pairs | From fixture transcripts |
| **LLM streaming** | Tokens with known sentence boundaries | For testing sentence-chunking |
| **TTS** | Chunks with known timing (200ms each) | For barge-in jitter testing |
| **Audio clock** | `unittest.mock.patch('time.monotonic')` | Deterministic timing for barge-in tests |

### 8.6 Coverage Requirements

| Module | Target | Notes |
|---|---|---|
| `core/state_machine.py` | **100% branches, 100% transitions** | Every valid AND invalid transition tested |
| `core/pipeline.py` | 95% branches | All streaming paths, barge-in, cold-start |
| `routes/ws.py` (streaming) | 95% branches | Concurrent connection handling |
| Latency budget assertions | Measured, not asserted strictly in CI | CI variance too high; measure and alert on regression |

### 8.7 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `vad_speech_pattern_utterance1` | Timestamped VAD results for a 3-second utterance: `[(0.0, False), (0.3, True), (3.2, False)]` |
| `vad_speech_pattern_interruption` | User speaks during playback: VAD triggers at specific offset |
| `stt_partial_sequence` | Ordered partial transcripts: `[("I", 0.1), ("I think", 0.2), ("I think this", 0.3), ..., ("I think this is a test", 1.0)]` |
| `llm_sentence_stream` | LLM tokens with sentence boundaries: `["The", " weather", " is", " sunny", ".",  "The", " temperature", " is", " 72", "."]` |
| `tts_chunk_sequence` | Pre-computed TTS audio chunks (200ms each) with known byte sizes |
| `wake_word_trigger_timestamps` | Timestamps where wake word fires in a test scenario |
| `transition_matrix_cases` | Programmatic list of all (from_state, event, to_state) tuples for parametrized testing |

### 8.8 Done Criteria (Test-Specific)

- [ ] All 34+ state machine transitions tested exhaustively (valid + invalid)
- [ ] Barge-in: SPEAKING → INTERRUPTED → LISTENING tested with VAD timings
- [ ] LISTENING timeout: 5s silence → IDLE tested
- [ ] Sentence-chunked TTS: sentences synthesized and played independently
- [ ] Cold-start warm-up sequence tested (dummy request to LLM)
- [ ] Sliding-window truncation: context window overflow → oldest turns dropped correctly
- [ ] **Total perceived latency < 1.5s** measured with mocked models (pipeline overhead only)
- [ ] Concurrent barge-in during state transition doesn't cause crash or lost state

### 8.9 Key Test Patterns for Phase 3

```python
import pytest
from shared.state import FSMState, StateMachine, InvalidTransitionError


class TestStateMachineExhaustive:
    """Exhaustive transition matrix tests."""

    @pytest.fixture
    def sm(self):
        return StateMachine()

    @pytest.mark.parametrize("from_state,event,to_state", [
        # Valid transitions from transition matrix
        (FSMState.IDLE, "wake_word_detected", FSMState.LISTENING),
        (FSMState.IDLE, "vad_speech_start", FSMState.LISTENING),
        (FSMState.IDLE, "timeout", FSMState.ERROR),
        (FSMState.LISTENING, "end_of_speech", FSMState.PROCESSING),
        (FSMState.LISTENING, "timeout", FSMState.IDLE),
        (FSMState.PROCESSING, "first_sentence_ready", FSMState.SPEAKING),
        (FSMState.PROCESSING, "tool_call", FSMState.TOOL_WAITING),
        (FSMState.PROCESSING, "vad_speech_start", FSMState.INTERRUPTED),
        (FSMState.SPEAKING, "vad_speech_start", FSMState.INTERRUPTED),
        (FSMState.SPEAKING, "tts_complete", FSMState.IDLE),
        (FSMState.INTERRUPTED, "vad_stop", FSMState.LISTENING),
        (FSMState.TOOL_WAITING, "tool_result_received", FSMState.PROCESSING),
        (FSMState.ERROR, "recovery_success", FSMState.IDLE),
        (FSMState.ERROR, "recovery_timeout", FSMState.ERROR),
    ])
    def test_valid_transition(self, sm, from_state, event, to_state):
        """Each valid transition moves to the correct next state."""
        sm._state = from_state
        sm.transition(event)
        assert sm.state == to_state

    @pytest.mark.parametrize("from_state,event", [
        # Invalid transitions from transition matrix
        (FSMState.IDLE, "end_of_speech"),
        (FSMState.IDLE, "llm_token"),
        (FSMState.LISTENING, "llm_token"),
        (FSMState.SPEAKING, "end_of_speech"),
    ])
    def test_invalid_transition_raises(self, sm, from_state, event):
        """Invalid transitions raise InvalidTransitionError."""
        sm._state = from_state
        with pytest.raises(InvalidTransitionError):
            sm.transition(event)

    def test_listening_timeout(self, sm):
        """LISTENING -> IDLE after 5s timeout."""
        sm._state = FSMState.LISTENING
        sm.transition("timeout")
        assert sm.state == FSMState.IDLE

    def test_barge_in_flow(self, sm):
        """Full barge-in: SPEAKING -> INTERRUPTED -> LISTENING."""
        sm._state = FSMState.SPEAKING
        sm.transition("vad_speech_start")
        assert sm.state == FSMState.INTERRUPTED
        sm.transition("vad_stop")
        assert sm.state == FSMState.LISTENING

    def test_any_state_to_error(self, sm):
        """ANY state can transition to ERROR on component failure."""
        for state in FSMState:
            if state != FSMState.ERROR:
                sm._state = state
                sm.transition("component_failure")
                assert sm.state == FSMState.ERROR
                sm._state = FSMState.ERROR
                sm.transition("recovery_success")
                assert sm.state == FSMState.IDLE

    def test_event_callbacks_fire(self, sm):
        """Callbacks registered for events fire on transition."""
        callbacks = []
        sm.on_transition(lambda from_s, to_s, event: callbacks.append((from_s, to_s, event)))
        sm._state = FSMState.IDLE
        sm.transition("wake_word_detected")
        assert len(callbacks) == 1
        assert callbacks[0] == (FSMState.IDLE, FSMState.LISTENING, "wake_word_detected")

    def test_concurrent_event_safety(self, sm):
        """Simultaneous events don't corrupt state machine."""
        import asyncio
        sm._state = FSMState.SPEAKING
        async def fire_barge_in():
            sm.transition("vad_speech_start")
        async def fire_tts_complete():
            sm.transition("tts_complete")
        # Run concurrently — only one should succeed
        results = asyncio.gather(
            fire_barge_in(),
            fire_tts_complete(),
            return_exceptions=True
        )
        successes = [r for r in results if r is None or r is True]
        exceptions = [r for r in results if isinstance(r, InvalidTransitionError)]
        assert len(successes) == 1  # Only one transition succeeded
        assert len(exceptions) == 1  # The other was rejected
        assert sm.state in (FSMState.INTERRUPTED, FSMState.IDLE)


class TestLatencyBudget:
    """Latency budget assertions for Phase 3."""

    async def test_first_stt_partial_under_150ms(self, mock_pipeline):
        """End of speech -> first STT partial under 150ms."""
        import time
        start = time.monotonic()
        result = await mock_pipeline.process_audio_chunk(b"audio_data")
        elapsed = (time.monotonic() - start) * 1000
        assert elapsed < 150, f"STT TTFT {elapsed:.1f}ms > 150ms"

    async def test_tts_first_byte_under_200ms(self, mock_pipeline, mock_llm_sentence):
        """First LLM sentence -> first TTS byte under 200ms."""
        start = time.monotonic()
        chunks = []
        async for chunk in mock_pipeline.synthesize_sentence(mock_llm_sentence):
            chunks.append(chunk)
            break  # Only need first chunk
        elapsed = (time.monotonic() - start) * 1000
        assert elapsed < 200, f"TTS TTFT {elapsed:.1f}ms > 200ms"
```

---

## 9. Phase 4 — Memory

> **Goal:** Short-term (session buffer) + long-term (vector DB) memory.
> **Implementation tasks:** [Phase 4 in schedule.md](./schedule.md#phase-4--memory)

### 9.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/memory/src/short_term.py` | `memory/test_short_term.py` | — Sliding window keeps last N turns<br>— Window size configurable<br>— Turns beyond window are dropped (oldest first)<br>— Empty buffer returns empty list<br>— Buffer correctly serializes/deserializes from Redis<br>— Running summary generation (compression of older turns) |
| `services/memory/src/long_term.py` | `memory/test_long_term.py` | — Embedding + storage in ChromaDB<br>— Semantic search returns top-k results<br>— Empty collection returns empty results<br>— Relevance threshold filter (skip low-similarity results)<br>— Deletion of specific memory entries<br>— Collection persistence/reload (in ephemeral mode) |
| `services/memory/src/extraction.py` | `memory/test_extraction.py` | — "Is this worth remembering?" heuristic/LLM call<br>— Fact extraction from conversation turn<br>— JSON schema for extracted facts<br>— Empty conversation yields no facts<br>— Importance scoring (0.0-1.0) |
| `services/orchestrator/src/clients/memory.py` | `orchestrator/clients/test_memory_client.py` | — `MEMORY_STORE` message correctly formatted<br>— `MEMORY_RETRIEVE` sent with query<br>— `MEMORY_RETRIEVE_RESULT` parsed into facts<br>— Timeout on memory service raises `MemoryTimeoutError` |

### 9.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| Memory service with in-memory ChromaDB | — Store fact → Retrieve fact by query → Retrieved matches stored |
| Redis short-term buffer | — Store turns → Retrieve turns → Correct ordering and count |
| Orchestrator ↔ Memory via Redis Streams | — Create conversation → memory extraction fires → facts stored → next query retrieves relevant facts |

### 9.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_memory_recall.py` (in Phase 3 E2E suite) | — User states "My dog's name is Max"<br>— Later asks "What's my dog's name?" → Assistant answers "Max"<br>— Multi-session recall (facts persist across conversation restarts) |

### 9.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **ChromaDB** | `chromadb.Client.__init__` with `EphemeralClient` | In-memory, no persistence needed for tests |
| **Redis** | `fakeredis` | For short-term buffer tests |
| **LLM for extraction** | AsyncMock returning structured JSON | "Is this worth remembering?" call mocked |
| **Embedding model** | Mock returning pre-computed embedding vectors | Avoid loading embedding models in CI |
| **Memory retrieval** | Pre-computed fact list from fixture | Return consistent results across test runs |

### 9.5 Coverage Requirements

| Module | Target |
|---|---|
| `memory/src/short_term.py` | 95% branches |
| `memory/src/long_term.py` | 95% branches, 100% ChromaDB operation paths |
| `memory/src/extraction.py` | 90% branches |
| `clients/memory.py` | 90% branches |

### 9.6 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `conversation_turns_5` | 5 turns of conversation for short-term buffer tests |
| `conversation_turns_15` | 15 turns (exceeds default window) for truncation tests |
| `known_facts` | List of dicts: `[{"text": "User's dog is named Max", "importance": 0.9, "category": "personal"}, ...]` |
| `precomputed_embeddings` | Dict mapping fact text → embedding vector (128-dim float list) |
| `chromadb_ephemeral` | `chromadb.EphemeralClient` fixture with seeded data |
| `memory_query_results` | Pre-computed retrieval results for given queries |

### 9.7 Done Criteria (Test-Specific)

- [ ] Short-term buffer correctly maintains sliding window of last N turns
- [ ] Running summary generated when buffer exceeds configurable token limit
- [ ] Long-term memory stores and retrieves facts with >90% precision@5
- [ ] Memory extraction fires after configurable interval (every N turns)
- [ ] Retrieved memory injected into system prompt (Phase 4 of prompt building)
- [ ] Memory retrieval capped to configurable max facts (3-5 default)
- [ ] `MEMORY_STORE`, `MEMORY_RETRIEVE`, `MEMORY_RETRIEVE_RESULT` messages flow correctly

### 9.8 Key Test Patterns for Phase 4

```python
import pytest
import chromadb
from memory.short_term import ShortTermBuffer
from memory.long_term import LongTermMemory
from memory.extraction import MemoryExtractor


class TestShortTermBuffer:
    """Sliding window conversation buffer tests."""

    def test_keeps_last_n_turns(self):
        """Buffer maintains exactly N most recent turns."""
        buffer = ShortTermBuffer(window_size=5)
        for i in range(10):
            buffer.add(f"User: turn {i}", f"Assistant: response {i}")
        assert len(buffer.get_turns()) == 5
        assert buffer.get_turns()[-1] == ("User: turn 9", "Assistant: response 9")

    def test_window_size_configurable(self):
        """Window size is configurable at init."""
        buffer = ShortTermBuffer(window_size=3)
        for i in range(5):
            buffer.add(f"Q{i}", f"A{i}")
        assert len(buffer.get_turns()) == 3

    def test_empty_buffer_returns_empty(self):
        """Fresh buffer returns empty list."""
        buffer = ShortTermBuffer()
        assert buffer.get_turns() == []

    def test_buffer_serialization(self):
        """Buffer serializes to JSON for Redis storage."""
        buffer = ShortTermBuffer(window_size=2)
        buffer.add("Hello", "Hi there")
        data = buffer.serialize()
        restored = ShortTermBuffer.deserialize(data)
        assert restored.get_turns() == buffer.get_turns()


class TestLongTermMemory:
    """Long-term memory with ChromaDB (ephemeral, in-memory)."""

    @pytest.fixture
    def memory(self):
        client = chromadb.EphemeralClient()
        return LongTermMemory(client=client, collection_name="test_memories")

    async def test_store_and_retrieve(self, memory, known_facts):
        """Stored facts are retrievable by semantic search."""
        for fact in known_facts:
            await memory.store(text=fact["text"], metadata={"importance": fact["importance"]})
        results = await memory.retrieve("What is my dog's name?", top_k=3)
        assert len(results) > 0
        assert any("Max" in r["text"] for r in results)

    async def test_empty_collection_returns_empty(self, memory):
        """Querying empty collection returns empty list."""
        results = await memory.retrieve("anything", top_k=5)
        assert results == []

    async def test_top_k_respected(self, memory, known_facts):
        """Result count does not exceed top_k."""
        for fact in known_facts:
            await memory.store(text=fact["text"], metadata={})
        results = await memory.retrieve("test", top_k=2)
        assert len(results) <= 2


class TestMemoryExtraction:
    """Memory extraction from conversation turns."""

    async def test_extracts_facts_from_conversation(self, mock_llm_extraction):
        """Conversation turn produces structured facts."""
        extractor = MemoryExtractor(llm_client=mock_llm_extraction)
        facts = await extractor.extract("User: My dog's name is Max\nAssistant: That's a great name!")
        assert len(facts) > 0
        assert any("Max" in f["text"] for f in facts)
        assert all(0.0 <= f["importance"] <= 1.0 for f in facts)

    async def test_empty_conversation_yields_no_facts(self, mock_llm_extraction):
        """No extractable facts returns empty list."""
        extractor = MemoryExtractor(llm_client=mock_llm_extraction)
        facts = await extractor.extract("User: Hi\nAssistant: Hello.")
        assert isinstance(facts, list)
```

---

## 10. Phase 5 — Tool Calling

> **Goal:** Function-calling layer, tool registry, safety tiers.
> **Implementation tasks:** [Phase 5 in schedule.md](./schedule.md#phase-5--tool-calling)

### 10.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/tools/src/registry.py` | `tools/test_registry.py` | — Tool registration (name → function + schema)<br>— Tool lookup by name<br>— Duplicate tool name raises `ToolRegistryError`<br>— List all registered tools<br>— Schema auto-generated from Pydantic model<br>— Argument validation against Pydantic schema |
| `services/tools/src/web_search.py` | `tools/test_web_search.py` | — SearXNG search returns results<br>— DuckDuckGo fallback works<br>— Empty query returns error, not crash<br>— Network error returns `ToolExecutionError`<br>— Results truncation (max N results) |
| `services/tools/src/file_io.py` | `tools/test_file_io.py` | — `read_file` reads file contents<br>— `read_file` rejects path traversal (`../../../etc/passwd`)<br>— `read_file` sandbox directory restriction<br>— `write_file` writes to allowed directory<br>— `write_file` rejects overwrite outside sandbox<br>— File size limits enforced |
| `services/tools/test_safety_tiers.py` | `tools/test_safety_tiers.py` | — **Safe** tools auto-execute without confirmation<br>— **Confirm** tools return confirmation required status<br>— **Restricted** tools checked against allowlist<br>— Restricted tool not in allowlist returns `ToolNotAllowedError`<br>— Safety tier configurable per tool |
| `services/orchestrator/src/clients/tools.py` | `orchestrator/clients/test_tools_client.py` | — Tool call message formatted correctly<br>— Tool result parsed and returned<br>— Timeout handling (`ToolTimeoutError`) |

### 10.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| Tool registry → tool execution (mocked) | — Registered tool call → arguments validated → result returned |
| Safety tier enforcement | — Safe tool executes immediately<br>— Confirm tool requires confirmation step<br>— Restricted tool blocked without allowlist entry |
| Tool call → LLM loop | — LLM issues tool call → tool executes → result injected back into LLM context |

### 10.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| `test_tool_calling.py` | — "What's the weather in London?" triggers `web_search` tool<br>— "Read my notes.txt" triggers `read_file` tool<br>— "Send an email" triggers confirm step (Phase 5 safety tier) |
| Tool confirmation interaction | — User says "Send an email to John" → Assistant asks "Shall I proceed?" → User says "Yes" → Email sends |

### 10.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **SearXNG** | Mock HTTP response with fixture search results | Return pre-computed results |
| **DuckDuckGo** | `duckduckgo_search` patched | Same approach |
| **Filesystem** | `pyfakefs` or `tempfile.TemporaryDirectory` | Sandboxed file operations |
| **LLM tool call format** | AsyncMock returning structured tool call | Simulate LLM requesting a tool |

### 10.5 Coverage Requirements

| Module | Target |
|---|---|
| `tools/src/registry.py` | 100% branches |
| `tools/src/web_search.py` | 90% branches |
| `tools/src/file_io.py` | 95% branches (sandbox path validation: 100%) |
| `tools/test_safety_tiers.py` | 100% branches on tier enforcement |

### 10.6 Test Fixtures Needed

| Fixture | Description |
|---|---|
| `tool_registry_with_3_tools` | Pre-registered: `web_search`, `read_file`, `get_datetime` |
| `mock_search_results` | JSON response from SearXNG with 5 mock results |
| `sandbox_directory` | `tempfile.TemporaryDirectory` for file I/O tests |
| `path_traversal_attempts` | `["../../../etc/passwd", "..\\..\\windows\\system32", "/etc/shadow", "....//....//etc/hosts"]` |
| `tool_safety_config` | Dict mapping tool name to tier + allowlist |

### 10.7 Done Criteria (Test-Specific)

- [ ] Tool registry: register, lookup, list, duplicate detection all tested
- [ ] Argument validation rejects invalid types and injection attempts
- [ ] Safe tools auto-execute; confirm tools require spoken confirmation; restricted tools check allowlist
- [ ] Path traversal attempts are all rejected with `ToolSandboxError`
- [ ] Web search returns structured results; network errors handled gracefully
- [ ] Tool call → execution → result → LLM feedback loop works
- [ ] All tool invocations logged with timestamp + arguments for audit trail

### 10.8 Key Test Patterns for Phase 5

```python
import pytest
from pydantic import BaseModel
from tools.registry import ToolRegistry, ToolRegistryError
from tools.safety_tiers import SafetyTier, SafetyEnforcer, ToolNotAllowedError


class TestToolRegistry:
    """Tool registration and lookup."""

    def test_register_and_call(self):
        """Tool can be registered with schema and called."""
        registry = ToolRegistry()

        class SearchArgs(BaseModel):
            query: str
            max_results: int = 5

        async def web_search(args: SearchArgs) -> dict:
            return {"results": [f"Result for {args.query}"]}

        registry.register("web_search", web_search, SearchArgs, tier=SafetyTier.SAFE)
        tool = registry.get("web_search")
        assert tool.name == "web_search"
        assert tool.schema_model == SearchArgs

    def test_duplicate_raises(self):
        """Registering same name twice raises ToolRegistryError."""
        registry = ToolRegistry()
        registry.register("test", lambda: None, BaseModel, tier=SafetyTier.SAFE)
        with pytest.raises(ToolRegistryError, match="already registered"):
            registry.register("test", lambda: None, BaseModel, tier=SafetyTier.SAFE)

    def test_unknown_tool_returns_none(self):
        """Getting unregistered tool returns None."""
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_list_returns_all(self):
        """list_tools returns all registered tool names."""
        registry = ToolRegistry()
        registry.register("a", lambda: None, BaseModel, tier=SafetyTier.SAFE)
        registry.register("b", lambda: None, BaseModel, tier=SafetyTier.CONFIRM)
        assert set(registry.list_tools()) == {"a", "b"}


class TestSafetyTiers:
    """Safety tier enforcement."""

    def test_safe_tool_auto_executes(self):
        """Safe tier tools execute without confirmation."""
        enforcer = SafetyEnforcer(allowlist=set())
        result = enforcer.check("web_search", SafetyTier.SAFE)
        assert result.allowed is True
        assert result.needs_confirmation is False

    def test_confirm_tool_needs_confirmation(self):
        """Confirm tier tools require verbal confirmation."""
        enforcer = SafetyEnforcer(allowlist=set())
        result = enforcer.check("send_email", SafetyTier.CONFIRM)
        assert result.allowed is True
        assert result.needs_confirmation is True

    def test_restricted_tool_not_in_allowlist(self):
        """Restricted tool without allowlist entry is blocked."""
        enforcer = SafetyEnforcer(allowlist=set())
        with pytest.raises(ToolNotAllowedError):
            enforcer.check("execute_command", SafetyTier.RESTRICTED)

    def test_restricted_tool_in_allowlist(self):
        """Restricted tool in allowlist is allowed (with confirmation)."""
        enforcer = SafetyEnforcer(allowlist={"execute_command"})
        result = enforcer.check("execute_command", SafetyTier.RESTRICTED)
        assert result.allowed is True
        assert result.needs_confirmation is True


class TestFileIOToolSandboxing:
    """File system sandbox enforcement."""

    def test_path_traversal_rejected(self, sandbox_directory, path_traversal_attempts):
        """All path traversal patterns are rejected."""
        from tools.file_io import FileIOTool
        tool = FileIOTool(sandbox_path=sandbox_directory)
        for attempt in path_traversal_attempts:
            with pytest.raises(ToolSandboxError):
                tool.validate_path(attempt)

    def test_sandboxed_file_read(self, sandbox_directory):
        """File within sandbox can be read."""
        from tools.file_io import FileIOTool
        test_file = Path(sandbox_directory) / "notes.txt"
        test_file.write_text("Hello from Jarvis")
        tool = FileIOTool(sandbox_path=sandbox_directory)
        content = tool.read_file(str(test_file))
        assert content == "Hello from Jarvis"
```

---

## 11. Phase 6 — Agentic + Robotics

> **Goal:** ReAct loop, ROS2 bridge, device control.
> **Implementation tasks:** [Phase 6 in schedule.md](./schedule.md#phase-6--agentic--robotics)

### 11.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| `services/orchestrator/src/core/pipeline.py` (ReAct) | `orchestrator/core/test_pipeline.py` (extended) | — Plan → Act → Observe → Replan loop<br>— Multiple tool calls chained before responding<br>— Max iterations limit prevents infinite loops<br>— Loop termination condition (LLM responds without tool call)<br>— Error in tool call replans (doesn't crash) |
| `services/tools/src/ros2_bridge.py` | `tools/test_ros2_bridge.py` | — Tool call → ROS2 topic publication<br>— ROS2 service call → result returned<br>— Bridge translates tool arguments to ROS2 message format<br>— Safety limits enforced (max velocity, forbidden zones)<br>— Connection failure raises `RobotBridgeError` |
| Safety enforcement for physical actions | `tools/test_safety_tiers.py` (extended) | — Physical action tools are RESTRICTED tier<br>— Allowlist checked for each physical action<br>— Velocity/force limits enforced in bridge (not in prompt) |

### 11.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| ReAct loop with mocked tools | — LLM calls tool → tool returns → LLM calls another tool → LLM responds<br>— Max iterations reached → loop terminates with fallback response |
| ROS2 bridge (mocked) | — Tool call translated to ROS2 message<br>— Result parsed from ROS2 response |

### 11.3 E2E Test Targets

> No browser-based E2E for robotics (hardware-dependent). Manual integration tests with real/simulated ROS2 environment.

### 11.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **ROS2** | `rclpy` node patched | Mock publisher/subscriber/service calls |
| **Ollama ReAct** | Multi-turn mock returning tool call → tool call → final response | Simulate ReAct loop iteration |
| **Robot hardware** | Mock sensor readings, mock actuator responses | Return pre-computed telemetry |

### 11.5 Coverage Requirements

| Module | Target |
|---|---|
| ReAct loop logic | 95% branches, max iteration edge cases |
| `ros2_bridge.py` | 85% branches (hardware-dependent paths skipped) |
| Physical safety enforcement | 100% branches on limit checks |

### 11.6 Done Criteria (Test-Specific)

- [ ] ReAct loop correctly chains multiple tool calls: plan → act → observe → replan
- [ ] Max iterations reached → loop terminates cleanly with fallback response
- [ ] Tool error causes replan, not crash
- [ ] ROS2 bridge translates tool call → ROS2 message → result
- [ ] Physical safety limits (velocity, force, zones) enforced in code, not prompt
- [ ] All physical action tools are RESTRICTED tier

---

## 12. Phase 7 — Deployment

> **Goal:** Docker, auth, observability.
> **Implementation tasks:** [Phase 7 in schedule.md](./schedule.md#phase-7--deployment)

### 12.1 Unit Test Targets

| Module | Test File | What to Verify |
|---|---|---|
| Auth middleware | `orchestrator/test_auth.py` | — Valid API key authenticates successfully<br>— Invalid API key returns 401<br>— Missing auth header returns 401<br>— API key loaded from env, not hardcoded<br>— Key rotation support (multiple valid keys) |
| Docker health checks | `test_health.py` (all services) | — `GET /health` returns 200 with dependencies<br>— `GET /health` returns 503 when critical dependency down<br>— Response matches expected JSON schema |
| Graceful shutdown | All service `test_main.py` | — SIGTERM → complete in-flight work → ack pending messages → close connections → exit<br>— Shutdown timeout enforced → force exit after timeout<br>— Double SIGTERM handled gracefully |

### 12.2 Integration Test Targets

| Test | What to Verify |
|---|---|
| Docker Compose stack boot | — `docker compose up` boots all services<br>— All health endpoints return 200 within startup timeout<br>— Service discovery works (services can reach Redis by hostname) |
| Cross-service auth | — Orchestrator rejects requests without valid API key<br>— WebSocket connections without token rejected at upgrade |

### 12.3 E2E Test Targets

| Test | What to Verify |
|---|---|
| Full stack smoke test | — All containers running → health check passes → basic chat works |
| Restart resilience | — Service crash → Docker restarts → state preserved<br>— Redis restart → services reconnect and resume |
| Observability | — Logs emitted in JSON format<br>— Request correlation ID flows through all services<br>— Prometheus metrics endpoint responds |

### 12.4 Mocking Strategy

| Dependency | Mock | Details |
|---|---|---|
| **Docker** | `docker-py` mock | For testing Docker SDK usage (if any) |
| **Auth** | Test API key fixture | Hardcoded for test environment |

### 12.5 Coverage Requirements

| Module | Target |
|---|---|
| Auth middleware | 100% branches on auth logic |
| Graceful shutdown | 95% branches on signal handling |
| Health endpoints | 100% lines on response formatting |

### 12.6 Done Criteria (Test-Specific)

- [ ] Auth middleware correctly validates API keys on all protected endpoints
- [ ] `docker compose up` boots full stack; all health checks pass
- [ ] Graceful shutdown: in-flight work completes, messages acknowledged, connections closed
- [ ] JSON logs emitted with correlation IDs across all services
- [ ] All ports bound to localhost only by default

---

## 13. Running Tests

### 13.1 Quick Start

```bash
# Install test dependencies
pip install -e "shared/[dev]"
pip install -e "services/*/[dev]"
pip install pytest pytest-asyncio pytest-cov pytest-mock fakeredis chromadb

# Run all unit tests (CI mode, no hardware, no slow tests)
pytest tests/ -m "not audio_hardware and not slow and not e2e" -v --cov

# Run single phase tests
pytest tests/shared/test_messages.py -v --cov=shared
pytest tests/services/orchestrator/ -v --cov=services/orchestrator
```

### 13.2 Phase-Specific Commands

```bash
# Phase 0: shared package + health + rate limiting
pytest tests/shared/ tests/services/*/test_health.py \
    tests/services/*/test_main.py -v --cov=shared --cov=services

# Phase 0.5: Audio primitives
pytest tests/shared/test_audio.py -v --cov=shared.audio

# Phase 0.5 audio hardware tests (manual, skipped in CI)
pytest tests/shared/test_audio.py -m audio_hardware -v

# Phase 1: LLM client, prompt assembly, chat endpoint
pytest tests/services/orchestrator/clients/test_llm_client.py \
    tests/services/orchestrator/core/test_prompt.py \
    tests/services/orchestrator/test_chat_endpoint.py -v --cov

# Phase 2: STT, TTS, VAD, WS auth
pytest tests/services/stt/ tests/services/tts/ \
    tests/services/orchestrator/test_ws_endpoint.py -v --cov

# Phase 3: State machine (exhaustive), streaming pipeline, latency
pytest tests/shared/test_state.py \
    tests/services/orchestrator/core/test_state_machine.py \
    tests/services/orchestrator/core/test_pipeline.py \
    tests/performance/test_latency_budget.py -v --cov

# Phase 4: Memory
pytest tests/services/memory/ -v --cov

# Phase 5: Tools
pytest tests/services/tools/ -v --cov

# Phase 6: ReAct, ROS2 bridge
pytest tests/services/orchestrator/core/test_pipeline.py -m react \
    tests/services/tools/test_ros2_bridge.py -v --cov

# Phase 7: Auth, health, graceful shutdown
pytest tests/services/*/test_auth.py tests/services/*/test_health.py -v --cov

# Full test suite (excluding hardware, E2E, slow)
pytest tests/ -m "not audio_hardware and not e2e and not slow" -v --cov

# Full test suite including E2E (requires Docker)
pytest tests/ -m "not audio_hardware" -v --cov

# Performance regression tests
pytest tests/performance/ -v --cov

# Coverage report with missing branch info
pytest --cov --cov-report=term-missing --cov-report=html
```

### 13.3 Test Markers Summary

| Marker | When to Use | CI Behavior |
|---|---|---|
| `pytest.mark.unit` | Pure unit tests (no external deps) | Always run |
| `pytest.mark.integration` | Tests touching databases/external services (mocked) | Always run |
| `pytest.mark.e2e` | Full end-to-end tests | Separate CI job |
| `pytest.mark.audio_hardware` | Tests requiring real mic/speaker | Skipped |
| `pytest.mark.slow` | Tests taking >5 seconds | Separate CI job |
| `pytest.mark.performance` | Latency/throughput regression tests | Alert-only |
| `pytest.mark.smoke` | Fast smoke tests (pre-merge gate) | Gating |
| `pytest.mark.flaky` | Known flaky tests needing investigation | Logged, not gating |

---

## 14. CI Integration

### 14.1 CI Workflow (`.github/workflows/ci.yml`)

```yaml
name: JARVIS CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

env:
  PYTHON_VERSION: "3.12"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install ruff mypy
      - run: ruff check . --output-format=github
      - run: mypy shared/src services/*/src --ignore-missing-imports

  unit-and-integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install dependencies
        run: |
          pip install -e "shared/[dev]"
          pip install -e "services/*/[dev]"
          pip install pytest pytest-asyncio pytest-cov pytest-mock fakeredis chromadb httpx
      - name: Run unit + integration tests
        run: |
          pytest tests/ \
            -m "not audio_hardware and not e2e and not slow and not performance" \
            --cov=shared \
            --cov=services \
            --cov-report=term \
            --cov-report=xml \
            --junitxml=test-results.xml
      - name: Check coverage
        run: |
          # Fail if any module below 80% coverage
          pytest --cov --cov-fail-under=80
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: test-results
          path: test-results.xml

  state-machine-exhaustive:
    runs-on: ubuntu-latest
    # Phase 3 state machine tests are critical — separate job for visibility
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install -e "shared/[dev]" pytest pytest-asyncio pytest-cov
      - name: Run state machine matrix tests
        run: |
          pytest tests/services/orchestrator/core/test_state_machine.py \
            -v --cov=orchestrator.core.state_machine --cov-report=term
      - name: Validate transition matrix completeness
        run: |
          python -c "
          from shared.state import FSMState
          # Verify all states are covered
          states = list(FSMState)
          assert len(states) == 7, f'Expected 7 states, got {len(states)}'
          print(f'✓ All {len(states)} states validated')
          "

  e2e:
    runs-on: ubuntu-latest
    needs: [unit-and-integration]
    services:
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping" --health-interval 5s
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install dependencies
        run: |
          pip install -e "shared/[dev]"
          pip install -e "services/*/[dev]"
          pip install pytest pytest-asyncio fakeredis
      - name: Run E2E tests
        run: |
          pytest tests/e2e/ -v --timeout=60
        env:
          REDIS_URL: redis://localhost:6379

  build:
    runs-on: ubuntu-latest
    needs: [unit-and-integration]
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker images
        run: |
          docker compose build --parallel
      - name: Smoke test Docker images
        run: |
          docker compose up -d
          # Wait for health checks
          sleep 10
          for service in orchestrator stt tts memory tools; do
            curl -f http://localhost:8000/health || exit 1
          done
          docker compose down

  performance:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install -e "shared/[dev]" pytest pytest-asyncio pytest-cov
      - name: Run performance regression tests
        run: |
          pytest tests/performance/ -v --cov --cov-report=term
        # Performance alerts are informational, not gating
        continue-on-error: true
```

### 14.2 Gating vs. Non-Gating Tests

| Stage | Tests | Gating? | Blocking |
|-------|-------|---------|----------|
| **Smoke** | Lint, type-check, fast unit tests | **YES** | Blocks merge |
| **Unit + Integration** | All unit & integration (excl. slow/e2e/hw) | **YES** | Blocks merge |
| **State Machine** | Exhaustive transition matrix | **YES** | Blocks merge |
| **Coverage** | 80%+ per module | **YES** | Blocks merge |
| **Build** | Docker images build + health-check | **YES** | Blocks merge |
| **E2E** | Full pipeline end-to-end | **YES** (but may retry) | Blocks merge after retry |
| **Performance** | Latency budget, throughput | **NO** | Alert only, tracked in dashboard |
| **Audio hardware** | Real mic/speaker tests | **NO** | Manual run only |

### 14.3 Pre-Merge Checklist (CI)

```yaml
# Gating: all of these must pass before merge
- ✅ Lint (ruff, mypy)
- ✅ Unit + Integration tests (all modules ≥80% coverage)
- ✅ State machine transition matrix (100% transitions tested)
- ✅ Docker images build
- ✅ E2E tests pass (1 retry allowed for flaky tests)
```

---

## 15. Test Fixtures Catalog

### 15.1 Audio Fixtures (`tests/fixtures/audio/`)

| File | Duration | Format | Description | Transcript |
|---|---|---|---|---|
| `speech_clean_16khz.wav` | 3.0s | 16kHz mono 16-bit PCM | Clean speech, quiet room | "Hello, this is a test utterance for the voice assistant." |
| `speech_clean_44khz.wav` | 3.0s | 44.1kHz mono 16-bit PCM | Same utterance, higher sample rate | "Hello, this is a test utterance for the voice assistant." |
| `speech_noisy_16khz.wav` | 4.0s | 16kHz mono 16-bit PCM | Speech with cafe background noise | "I need to check the weather for tomorrow's meeting." |
| `silence_1s_16khz.wav` | 1.0s | 16kHz mono 16-bit PCM | Complete silence | "" |
| `utterance_short_16khz.wav` | 0.8s | 16kHz mono 16-bit PCM | Very short utterance | "Yes." |
| `speech_loud_16khz.wav` | 2.5s | 16kHz mono 16-bit PCM | Loud speech (tests gain/level) | "TURN DOWN THE VOLUME PLEASE." |
| `speech_overlapping.wav` | 5.0s | 16kHz mono 16-bit PCM | Multiple speakers (tests VAD) | "Hello? [overlap] Hi there! [overlap] Can you hear me?" |

### 15.2 Transcript Fixtures (`tests/fixtures/transcripts/`)

| File | Contents |
|---|---|
| `known_transcripts.json` | Mapping: `{"speech_clean_16khz.wav": "Hello, this is a test utterance for the voice assistant.", ...}` |
| `conversation_3_turns.json` | 3-turn conversation for Phase 1 prompt tests |
| `conversation_10_turns.json` | 10-turn conversation for Phase 4 memory buffer tests |
| `conversation_context_overflow.json` | 25+ turns that exceed context window for truncation tests |
| `partial_transcripts.json` | Sequence of partial transcripts for streaming STT tests |

### 15.3 Memory Fixtures (`tests/fixtures/memory/`)

| File | Contents |
|---|---|
| `facts.json` | `[{"text": "User's dog is named Max", "importance": 0.9, "category": "personal", "timestamp": 1000.0}, ...]` (10+ facts) |
| `embeddings.json` | Dict mapping fact text → 128-dim embedding vector |
| `memory_queries.json` | `[{"query": "What is my dog's name?", "expected_fact": "User's dog is named Max", "min_similarity": 0.7}, ...]` |

### 15.4 Tool Fixtures (`tests/fixtures/tools/`)

| File | Contents |
|---|---|
| `weather_response.json` | Mock OpenWeatherMap / weather API response |
| `search_results.json` | Mock SearXNG / DuckDuckGo search results (5 results) |
| `tool_schemas.json` | Pydantic schemas for all tools (for registry tests) |

### 15.5 Message Fixtures (`tests/fixtures/messages/`)

| File | Contents |
|---|---|
| `valid_messages.json` | All 16 message types with valid payloads (one per type) |
| `invalid_messages.json` | Edge cases: empty request_id, negative timestamp, unknown type, extra fields, null payload |

---

## 16. TDD Workflow Guidelines

### 16.1 Standard TDD Cycle

```
┌──────────────────────────────────────────────────┐
│                  1. WRITE TEST                     │
│    (RED) — Write a failing test that describes     │
│    the expected behavior.                          │
│    ┌─────────────────────────────────────────┐     │
│    │ assert result == expected_value          │     │
│    └─────────────────────────────────────────┘     │
├──────────────────────────────────────────────────┤
│                  2. RUN TEST                       │
│    Verify it FAILS (pytest test_file.py)           │
│    ┌─────────────────────────────────────────┐     │
│    │ FAILED test_file.py::test_name —         │     │
│    │ AssertionError: assert None == ...       │     │
│    └─────────────────────────────────────────┘     │
├──────────────────────────────────────────────────┤
│               3. MINIMAL IMPLEMENTATION             │
│    (GREEN) — Write only enough code to pass.       │
│    ┌─────────────────────────────────────────┐     │
│    │ def function(): return expected_value   │     │
│    └─────────────────────────────────────────┘     │
├──────────────────────────────────────────────────┤
│                  4. RUN TEST                       │
│    Verify it PASSES                                 │
│    ┌─────────────────────────────────────────┐     │
│    │ PASSED test_file.py::test_name           │     │
│    └─────────────────────────────────────────┘     │
├──────────────────────────────────────────────────┤
│                 5. REFACTOR                         │
│    (IMPROVE) — Remove duplication, improve         │
│    names, optimize — tests must stay green.        │
├──────────────────────────────────────────────────┤
│              6. VERIFY COVERAGE                     │
│    pytest --cov --cov-fail-under=80                │
└──────────────────────────────────────────────────┘
```

### 16.2 Project-Specific TDD Rules

1. **Never write implementation before the test.** The test defines the contract. If you can't write a test for it, you don't understand what it should do.

2. **One assertion per test where possible.** Use parametrize for multiple inputs. Each test should verify one behavior.

3. **External dependencies must be mocked at the boundary.** Never let a unit test call a real API, database, or audio device. Use `unittest.mock.patch`, `fakeredis`, or `chromadb.EphemeralClient`.

4. **Test error paths first.** For every function, test what happens when input is invalid, dependencies fail, or timeouts occur. Error handling is as important as happy paths.

5. **State machine tests must be exhaustive.** Use the transition matrix in Section 8.2. Every valid AND invalid transition must have a parametrized test case. Missing a transition is a bug.

6. **Audio tests are deterministic by construction.** Use `FileAudioSource` for input, `NullAudioSink` for output, and pre-recorded WAV fixtures. Never depend on microphone availability or timing.

7. **Latency tests measure relative to baseline.** CI environments have variable performance. Record baseline latencies and test for regression (e.g., "this test must not be more than 20% slower than the recorded baseline"), not absolute thresholds.

8. **Tests must be independent.** No shared state between tests. Each test creates its own fixtures. Use `yield` fixtures for cleanup.

9. **Coverage is a floor, not a ceiling.** 80% is the minimum. Critical modules (messages, state machine, safety tiers) should target 100%.

### 16.3 Adding Tests During Development

When adding a new feature:

```bash
# 1. Write the test first
touch tests/services/orchestrator/core/test_new_feature.py

# 2. Write the test content with expected behavior
#    (import the class/function that doesn't exist yet)

# 3. Run — it should FAIL
pytest tests/services/orchestrator/core/test_new_feature.py -v
# → ModuleNotFoundError / ImportError  (GOOD — RED phase)

# 4. Create the implementation file
touch services/orchestrator/src/core/new_feature.py

# 5. Add minimal implementation
#    (just enough to make imports work and test pass)

# 6. Run — it should PASS
pytest tests/services/orchestrator/core/test_new_feature.py -v

# 7. Verify coverage
pytest --cov=services/orchestrator --cov-report=term-missing

# 8. Commit
git add -A && git commit -m "feat: add new feature with tests"
```

### 16.4 Code Review Checklist for Tests

When reviewing a PR, verify:

- [ ] Tests exist for all new public functions and classes
- [ ] Error paths are tested (not just happy path)
- [ ] Edge cases covered: null/empty, invalid types, boundary values
- [ ] External dependencies are mocked (no real API calls in CI)
- [ ] Tests are independent — no shared mutable state
- [ ] Assertions are specific (no `assert True` or `assert result`)
- [ ] Async tests use `async def` with `pytest-asyncio`
- [ ] Fixtures are scoped appropriately (function-scoped by default)
- [ ] Test names are descriptive (`test_function_condition_expected_result`)
- [ ] No hardcoded secrets or API keys in test files
- [ ] Coverage is ≥80% for the module being changed

---

## 17. Appendices

### Appendix A: Testing Glossary

| Term | Definition |
|---|---|
| **Unit test** | Tests a single function/class in isolation. All external deps mocked. |
| **Integration test** | Tests interaction between two or more components. External deps mocked at the network boundary (HTTP, Redis). |
| **E2E test** | Tests the full system from user input to output. All services running (with mocked AI models). |
| **Fake** | Lightweight implementation of an external dependency (e.g., `fakeredis`, `chromadb.EphemeralClient`). |
| **Mock** | Test double that records calls and returns configured values. Used for LLM, STT, TTS. |
| **Stub** | Test double that returns fixed values. Used for config, settings. |
| **Fixture** | Reusable test data or setup/teardown logic. |
| **Parametrize** | Run the same test with multiple inputs. |
| **Transition matrix** | Exhaustive table of (from_state, event, to_state) tuples for state machine testing. |
| **Deterministic test** | Produces the same result every run, regardless of environment. |

### Appendix B: Dependency Injection Patterns for Testability

```python
# GOOD — dependencies injectable for testing
class Orchestrator:
    def __init__(self, llm_client: LLMClient, redis_client: Redis, stt_client: STTClient):
        self.llm = llm_client
        self.redis = redis_client
        self.stt = stt_client

# Test usage
async def test_orchestrator_with_mocks():
    mock_llm = AsyncMock(spec=LLMClient)
    mock_redis = FakeRedis()
    mock_stt = AsyncMock(spec=STTClient)
    orch = Orchestrator(llm_client=mock_llm, redis_client=mock_redis, stt_client=mock_stt)

# BAD — hardcoded dependencies, untestable
class Orchestrator:
    def __init__(self):
        self.llm = OllamaClient()  # Can't swap for mock
        self.redis = Redis.from_url("redis://localhost")  # Can't mock
        self.stt = WhisperSTT()  # Can't stub
```

### Appendix C: Async Test Patterns

```python
# CORRECT — pytest-asyncio auto mode
async def test_streaming_response():
    """Use async def for async code; pytest-asyncio handles event loop."""
    client = LLMClient(provider="ollama")
    tokens = []
    async for token in client.generate("Hello"):
        tokens.append(token)
    assert len(tokens) > 0

# CORRECT — mocking async generators
async def test_with_mock_stream():
    """Mock streaming responses with AsyncMock."""
    mock_client = AsyncMock(spec=LLMClient)

    async def _mock_generate(*args, **kwargs):
        for token in ["Hello", " ", "World"]:
            yield token

    mock_client.generate = _mock_generate
    tokens = [t async for t in mock_client.generate("test")]
    assert "".join(tokens) == "Hello World"

# CORRECT — testing async context managers
async def test_async_context_manager():
    """Test async context manager lifecycle."""
    mock_conn = AsyncMock()
    mock_conn.__aenter__.return_value = mock_conn
    mock_conn.__aexit__.return_value = None
    async with mock_conn as conn:
        assert conn is mock_conn
```

### Appendix D: Coverage Configuration

```ini
# .coveragerc
[run]
source = shared/src,services/orchestrator/src,services/stt/src,services/tts/src,services/memory/src,services/tools/src
omit =
    */tests/*
    */__pycache__/*
    */.venv/*
    */site-packages/*
    conftest_*.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    def __str__
    raise NotImplementedError
    if __name__ == .__main__.:
    pass
    raise ImportError
```

### Appendix E: Performance Baseline Recording

```python
# tests/performance/record_baseline.py
"""Record performance baselines for regression detection."""
import json
import time
import pytest

BASELINE_FILE = "tests/performance/baselines.json"

async def record_latency(test_name, func, *args, **kwargs):
    """Run a function and record its latency."""
    start = time.monotonic()
    await func(*args, **kwargs)
    elapsed = time.monotonic() - start
    return elapsed

@pytest.mark.performance
async def test_record_llm_token_latency():
    """Record baseline LLM token generation latency."""
    from orchestrator.clients.llm import LLMClient
    client = LLMClient(provider="ollama")  # Mocked in CI
    elapsed = await record_latency("llm_token_gen", client.generate, "Hello")
    assert elapsed < 0.5  # Sanity check
```

---

*End of test specification document. This document should be kept in sync with `jarvis_blueprint.md` as phases evolve.*
