from __future__ import annotations

import hashlib
import re
from pathlib import Path

from shared.logging import get_logger

logger = get_logger("orchestrator.prompt")


class ConversationBuffer:
    """Sliding-window conversation history.

    Maintains a list of turns with automatic truncation when the total
    token count exceeds max_context_tokens. Drops oldest complete turns
    first (never splits a turn).
    """

    def __init__(self, max_context_tokens: int = 4096) -> None:
        self._turns: list[dict[str, str]] = []
        self._max_context_tokens = max_context_tokens

    def add_turn(self, role: str, content: str) -> None:
        self._turns.append({"role": role, "content": content})
        self._truncate()

    def get_messages(
        self, system_prompt: str | None = None
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self._turns)
        return messages

    def clear(self) -> None:
        self._turns.clear()

    @property
    def turns(self) -> list[dict[str, str]]:
        return list(self._turns)

    @property
    def max_context_tokens(self) -> int:
        return self._max_context_tokens

    def _estimate_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3 + len(text) // 10)

    def _truncate(self) -> None:
        total = sum(self._estimate_tokens(t["content"]) for t in self._turns)
        while total > self._max_context_tokens and len(self._turns) > 1:
            dropped = self._turns.pop(0)
            total -= self._estimate_tokens(dropped["content"])


class PromptManager:
    VERSION = "v1_system"

    def __init__(
        self,
        prompts_dir: str | Path = "config/prompts",
        max_context_tokens: int = 4096,
    ) -> None:
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[str, str] = {}
        self._version_hash: str | None = None
        self._buffer = ConversationBuffer(max_context_tokens=max_context_tokens)

    @property
    def buffer(self) -> ConversationBuffer:
        return self._buffer

    def load(self, template_name: str = "v1_system") -> str:
        if template_name in self._cache:
            return self._cache[template_name]

        path = self.prompts_dir / f"{template_name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")

        template = path.read_text(encoding="utf-8")
        self._cache[template_name] = template
        self._version_hash = None
        logger.info(
            "prompt template loaded",
            name=template_name,
            version=self.VERSION,
            path=str(path),
        )
        return template

    def render(self, template_name: str = "v1_system", **kwargs: str) -> str:
        template = self.load(template_name)
        if "history" not in kwargs:
            history = self._format_history()
            kwargs["history"] = history

        def _replace(m: re.Match) -> str:
            key = m.group(1)
            return kwargs.get(key, m.group(0))

        return re.sub(r"\{(\w+)\}", _replace, template)

    @property
    def version_hash(self) -> str:
        if self._version_hash is None:
            digester = hashlib.sha256()
            for name in sorted(self._cache):
                digester.update(self._cache[name].encode())
            self._version_hash = digester.hexdigest()[:12]
        return self._version_hash

    def get_system_prompt(self, template_name: str = "v1_system") -> str:
        return self.load(template_name)

    def invalidate_cache(self, name: str | None = None) -> None:
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
        self._version_hash = None

    def add_user_turn(self, content: str) -> None:
        self._buffer.add_turn("user", content)

    def add_assistant_turn(self, content: str) -> None:
        self._buffer.add_turn("assistant", content)

    def build_messages(self) -> list[dict[str, str]]:
        system_prompt = self.get_system_prompt()
        return self._buffer.get_messages(system_prompt=system_prompt)

    def clear_history(self) -> None:
        self._buffer.clear()

    def _format_history(self) -> str:
        lines: list[str] = []
        for turn in self._buffer.turns:
            role = turn["role"].capitalize()
            lines.append(f"{role}: {turn['content']}")
        return "\n".join(lines)
