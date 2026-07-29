from __future__ import annotations

import pytest
from pydantic import ValidationError
from shared.messages import Message, MessageType, create_message

MESSAGE_TYPES = [
    (MessageType.TRANSCRIPT_PARTIAL, {"text": "hello", "language": "en"}),
    (
        MessageType.TRANSCRIPT_FINAL,
        {"text": "hello world", "language": "en", "confidence": 0.95},
    ),
    (MessageType.VAD_SPEECH_START, {}),
    (MessageType.VAD_SPEECH_END, {"duration_ms": 1200}),
    (MessageType.TTS_SYNTHESIZE, {"text": "Hello there", "voice": "default"}),
    (MessageType.TTS_STOP, {}),
    (
        MessageType.TTS_AUDIO_CHUNK,
        {"audio": "base64encodedbytes", "sequence": 1, "is_final": False},
    ),
    (MessageType.TTS_COMPLETE, {"total_chunks": 15, "duration_ms": 3200}),
    (MessageType.LLM_GENERATE, {"prompt": "Hello", "max_tokens": 256}),
    (MessageType.LLM_CANCEL, {"reason": "barge_in"}),
    (MessageType.LLM_TOKEN, {"token": "Hello", "index": 0}),
    (MessageType.LLM_COMPLETE, {"finish_reason": "stop", "total_tokens": 42}),
    (
        MessageType.LLM_TOOL_CALL,
        {"tool": "web_search", "arguments": {"query": "weather"}},
    ),
    (
        MessageType.MEMORY_STORE,
        {"facts": [{"text": "User likes coffee", "importance": 0.8}]},
    ),
    (MessageType.MEMORY_RETRIEVE, {"query": "What do I like?", "top_k": 5}),
    (MessageType.MEMORY_RETRIEVE_RESULT, {"facts": [], "query": "What do I like?"}),
]


@pytest.mark.parametrize("msg_type,payload", MESSAGE_TYPES)
def test_message_type_roundtrip(msg_type: MessageType, payload: dict) -> None:
    msg = Message(type=msg_type, payload=payload, request_id="test-1", timestamp=1000.0)
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored == msg
    assert restored.type == msg_type
    assert restored.request_id == "test-1"


def test_invalid_message_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(type="invalid_type", payload={}, request_id="test-1", timestamp=1.0)


def test_missing_required_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Message.model_validate({})


def test_extra_fields_rejected() -> None:
    msg = Message(
        type=MessageType.TRANSCRIPT_FINAL,
        payload={},
        request_id="test-1",
        timestamp=1.0,
    )
    data = msg.model_dump()
    data["extra_field"] = "should_not_be_here"
    restored = Message.model_validate(data)
    assert not hasattr(restored, "extra_field")


def test_request_id_non_empty() -> None:
    with pytest.raises(ValidationError):
        Message(
            type=MessageType.TRANSCRIPT_FINAL, payload={}, request_id="", timestamp=1.0
        )


def test_timestamp_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Message(
            type=MessageType.TRANSCRIPT_FINAL,
            payload={},
            request_id="test-1",
            timestamp=-1.0,
        )


def test_create_message_helper() -> None:
    msg = create_message(MessageType.VAD_SPEECH_START, payload={"duration_ms": 500})
    assert msg.type == MessageType.VAD_SPEECH_START
    assert msg.payload == {"duration_ms": 500}
    assert msg.request_id
    assert msg.timestamp > 0


def test_create_message_default_payload() -> None:
    msg = create_message(MessageType.TTS_STOP)
    assert msg.payload == {}


def test_create_message_with_session() -> None:
    msg = create_message(
        MessageType.TRANSCRIPT_FINAL, session_id="sess-1", user_id="user-1"
    )
    assert msg.session_id == "sess-1"
    assert msg.user_id == "user-1"


def test_llm_tool_call_payload_validation() -> None:
    msg = Message(
        type=MessageType.LLM_TOOL_CALL,
        payload={"tool": "web_search", "arguments": {"query": "weather in London"}},
        request_id="test-1",
        timestamp=1.0,
    )
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored.payload["tool"] == "web_search"
    assert restored.payload["arguments"]["query"] == "weather in London"
