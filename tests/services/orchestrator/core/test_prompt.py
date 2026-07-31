from __future__ import annotations

from pathlib import Path

import pytest
from orchestrator.core.prompt import ConversationBuffer, PromptManager

# --- PromptManager existing tests (unchanged) ---


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "prompts"
    d.mkdir()
    return d


@pytest.fixture
def pm(prompts_dir: Path) -> PromptManager:
    return PromptManager(prompts_dir=str(prompts_dir))


def test_load_template(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "test.md").write_text("Hello {name}")
    result = pm.load("test")
    assert result == "Hello {name}"


def test_load_missing_raises(pm: PromptManager) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        pm.load("nonexistent")


def test_render_substitutes(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "greet.md").write_text("Hello {name}, you are {age} years old")
    result = pm.render("greet", name="Alice", age="30")
    assert result == "Hello Alice, you are 30 years old"


def test_render_missing_key_raises(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "test.md").write_text("Hello {name}")
    result = pm.render("test")
    assert result == "Hello {name}"


def test_cache_hit(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "test.md").write_text("original")
    pm.load("test")
    (prompts_dir / "test.md").write_text("modified")
    result = pm.load("test")
    assert result == "original"


def test_cache_clear(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "test.md").write_text("original")
    pm.load("test")
    pm.invalidate_cache()
    (prompts_dir / "test.md").write_text("modified")
    result = pm.load("test")
    assert result == "modified"


def test_version_hash_stable(pm: PromptManager, prompts_dir: Path) -> None:
    (prompts_dir / "a.md").write_text("content A")
    (prompts_dir / "b.md").write_text("content B")
    pm.load("a")
    pm.load("b")
    h1 = pm.version_hash
    pm.invalidate_cache()
    pm.load("a")
    pm.load("b")
    h2 = pm.version_hash
    assert h1 == h2


def test_version_hash_changes_when_content_changes(
    pm: PromptManager, prompts_dir: Path
) -> None:
    (prompts_dir / "test.md").write_text("version 1")
    pm.load("test")
    h1 = pm.version_hash
    pm.invalidate_cache()
    (prompts_dir / "test.md").write_text("version 2")
    pm.load("test")
    h2 = pm.version_hash
    assert h1 != h2


def test_version_constant(pm: PromptManager) -> None:
    assert PromptManager.VERSION == "v1_system"


# --- ConversationBuffer tests ---


class TestConversationBuffer:
    def test_buffer_add_turn(self) -> None:
        buf = ConversationBuffer(max_context_tokens=4096)
        buf.add_turn("user", "hello")
        buf.add_turn("assistant", "hi there")
        assert len(buf.turns) == 2
        assert buf.turns[0] == {"role": "user", "content": "hello"}
        assert buf.turns[1] == {"role": "assistant", "content": "hi there"}

    def test_buffer_get_messages_without_system(self) -> None:
        buf = ConversationBuffer()
        buf.add_turn("user", "hello")
        buf.add_turn("assistant", "world")
        msgs = buf.get_messages()
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "hello"}

    def test_buffer_get_messages_with_system(self) -> None:
        buf = ConversationBuffer()
        buf.add_turn("user", "hello")
        msgs = buf.get_messages(system_prompt="You are a bot")
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "You are a bot"}
        assert msgs[1] == {"role": "user", "content": "hello"}

    def test_buffer_clear(self) -> None:
        buf = ConversationBuffer()
        buf.add_turn("user", "hello")
        buf.add_turn("assistant", "world")
        buf.clear()
        assert buf.turns == []

    def test_buffer_truncation_drops_oldest_pairs(self) -> None:
        buf = ConversationBuffer(max_context_tokens=30)
        for _ in range(10):
            buf.add_turn("user", "some words here for context")
            buf.add_turn("assistant", "more words here as the response")
        assert len(buf.turns) < 20
        assert len(buf.turns) > 0
        assert all(t["role"] in ("user", "assistant") for t in buf.turns)

    def test_buffer_no_truncation_under_budget(self) -> None:
        buf = ConversationBuffer(max_context_tokens=5000)
        for i in range(5):
            buf.add_turn("user", f"turn {i}")
            buf.add_turn("assistant", f"response {i}")
        assert len(buf.turns) == 10
        assert buf.turns[0]["content"] == "turn 0"

    def test_buffer_large_turn_not_split(self) -> None:
        buf = ConversationBuffer(max_context_tokens=50)
        huge = "word " * 100
        buf.add_turn("user", huge)
        assert len(buf.turns) == 1
        assert buf.turns[0]["content"] == huge

    def test_buffer_large_turn_preserves_single_over_budget(self) -> None:
        buf = ConversationBuffer(max_context_tokens=10)
        buf.add_turn("user", "tiny")
        huge = "word " * 50
        buf.add_turn("assistant", huge)
        assert len(buf.turns) >= 1
        assert buf.turns[-1]["content"] == huge

    def test_token_estimate_reasonable(self) -> None:
        buf = ConversationBuffer()
        text = "hello world this is a test " * 20
        estimated = buf._estimate_tokens(text)
        actual_tokens = len(text.split())
        assert estimated >= actual_tokens
        assert estimated <= actual_tokens * 3


# --- PromptManager integration tests ---


class TestPromptManagerConversation:
    def test_prompt_manager_add_turn_and_build_messages(
        self, prompts_dir: Path
    ) -> None:
        (prompts_dir / "v1_system.md").write_text("You are a helpful assistant.")
        pm = PromptManager(prompts_dir=str(prompts_dir))
        pm.add_user_turn("hello")
        pm.add_assistant_turn("hi!")
        msgs = pm.build_messages()
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": "hello"}
        assert msgs[2] == {"role": "assistant", "content": "hi!"}

    def test_prompt_manager_clear_history(self, prompts_dir: Path) -> None:
        (prompts_dir / "v1_system.md").write_text("You are a helpful assistant.")
        pm = PromptManager(prompts_dir=str(prompts_dir))
        pm.add_user_turn("hello")
        pm.clear_history()
        msgs = pm.build_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"

    def test_prompt_manager_integration_full_cycle(self, prompts_dir: Path) -> None:
        (prompts_dir / "v1_system.md").write_text("System prompt")
        pm = PromptManager(prompts_dir=str(prompts_dir))

        pm.add_user_turn("What is 2+2?")
        msgs_before = pm.build_messages()
        assert len(msgs_before) == 2
        assert msgs_before[1]["content"] == "What is 2+2?"

        pm.add_assistant_turn("4")
        msgs_after = pm.build_messages()
        assert len(msgs_after) == 3
        assert msgs_after[2]["content"] == "4"

    def test_prompt_manager_history_in_render(self, prompts_dir: Path) -> None:
        (prompts_dir / "v1_system.md").write_text("History:\n{history}")
        pm = PromptManager(prompts_dir=str(prompts_dir))
        pm.add_user_turn("hello")
        pm.add_assistant_turn("world")
        result = pm.render()
        assert "User: hello" in result
        assert "Assistant: world" in result

    def test_prompt_manager_max_context_tokens_from_settings(
        self, prompts_dir: Path
    ) -> None:
        pm = PromptManager(prompts_dir=str(prompts_dir), max_context_tokens=100)
        assert pm.buffer.max_context_tokens == 100

    def test_prompt_manager_buffer_property(self, prompts_dir: Path) -> None:
        pm = PromptManager(prompts_dir=str(prompts_dir))
        assert isinstance(pm.buffer, ConversationBuffer)
