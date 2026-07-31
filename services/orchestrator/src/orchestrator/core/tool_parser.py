from __future__ import annotations

import re

SEARCH_RE = re.compile(r"\[SEARCH:\s*(.+?)\s*\]", re.IGNORECASE)


class ToolCall:
    def __init__(self, tool: str, params: dict) -> None:
        self.tool = tool
        self.params = params

    def __repr__(self) -> str:
        """Return a debug-friendly representation of the tool call."""
        return f"ToolCall(tool={self.tool!r}, params={self.params!r})"


def parse_tool_calls(response_text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in SEARCH_RE.finditer(response_text):
        query = match.group(1).strip()
        if query:
            calls.append(
                ToolCall(tool="web_search", params={"query": query, "max_results": 5})
            )
    return calls


def strip_tool_markers(response_text: str) -> str:
    return SEARCH_RE.sub("", response_text).strip()
