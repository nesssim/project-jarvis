from __future__ import annotations

import hashlib
from pathlib import Path

from shared.logging import get_logger

logger = get_logger("orchestrator.prompt")


class PromptManager:
    VERSION = "v1_system"

    def __init__(self, prompts_dir: str | Path = "config/prompts") -> None:
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[str, str] = {}
        self._version_hash: str | None = None

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
        return template.format(**kwargs)

    @property
    def version_hash(self) -> str:
        if self._version_hash is None:
            digester = hashlib.sha256()
            for name in sorted(self._cache):
                digester.update(self._cache[name].encode())
            self._version_hash = digester.hexdigest()[:12]
        return self._version_hash

    def invalidate_cache(self, name: str | None = None) -> None:
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
        self._version_hash = None
