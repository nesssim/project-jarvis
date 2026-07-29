from __future__ import annotations

from pathlib import Path

import pytest

from services.orchestrator.src.orchestrator.core.prompt import PromptManager


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
    with pytest.raises(KeyError):
        pm.render("test")


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
