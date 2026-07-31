from __future__ import annotations

import re
from collections.abc import AsyncIterator

SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])[\"\'»„]?\s+(?=[A-Z\"'«»„])"
    r"|(?<=[.!?])(?=\Z)"
)


class SentenceChunker:
    def __init__(self, min_chars: int = 15, max_chars: int = 300) -> None:
        self._min_chars = min_chars
        self._max_chars = max_chars
        self._buffer = ""

    @property
    def is_empty(self) -> bool:
        return len(self._buffer) == 0

    async def add_token(self, token: str) -> AsyncIterator[str]:
        if not token or not token.strip():
            return
        self._buffer += token
        while len(self._buffer) >= self._min_chars:
            match = SENTENCE_BOUNDARY.search(self._buffer)
            if match:
                sentence = self._buffer[: match.end()]
                self._buffer = self._buffer[match.end() :]
                yield sentence.strip()
            elif len(self._buffer) >= self._max_chars:
                last_space = self._buffer.rfind(" ", 0, self._max_chars)
                if last_space > 0:
                    sentence = self._buffer[:last_space]
                    self._buffer = self._buffer[last_space:].lstrip()
                    yield sentence.strip()
                else:
                    sentence = self._buffer[: self._max_chars]
                    self._buffer = self._buffer[self._max_chars :]
                    yield sentence.strip()
            else:
                break

    async def flush(self) -> AsyncIterator[str]:
        if self._buffer.strip():
            yield self._buffer.strip()
            self._buffer = ""
