from __future__ import annotations

from orchestrator.core.tool_parser import parse_tool_calls, strip_tool_markers


class TestParseToolCalls:
    def test_detects_search_marker(self):
        calls = parse_tool_calls("Hello [SEARCH: latest news]")
        assert len(calls) == 1
        assert calls[0].tool == "web_search"
        assert calls[0].params["query"] == "latest news"

    def test_no_marker_returns_empty(self):
        calls = parse_tool_calls("Hello world")
        assert calls == []

    def test_case_insensitive(self):
        calls = parse_tool_calls("[search: python tutorials]")
        assert len(calls) == 1
        assert calls[0].params["query"] == "python tutorials"

    def test_multiple_markers(self):
        calls = parse_tool_calls(
            "[SEARCH: first] and [SEARCH: second]"
        )
        assert len(calls) == 2
        assert calls[0].params["query"] == "first"
        assert calls[1].params["query"] == "second"

    def test_empty_query_skipped(self):
        calls = parse_tool_calls("[SEARCH:  ]")
        assert calls == []

    def test_whitespace_handling(self):
        calls = parse_tool_calls("[SEARCH:   test query   ]")
        assert len(calls) == 1
        assert calls[0].params["query"] == "test query"


class TestStripToolMarkers:
    def test_removes_marker(self):
        result = strip_tool_markers("Hello [SEARCH: test]")
        assert result == "Hello"

    def test_removes_multiple_markers(self):
        result = strip_tool_markers("[SEARCH: a] middle [SEARCH: b]")
        assert "middle" in result

    def test_no_marker_unchanged(self):
        result = strip_tool_markers("Hello world")
        assert result == "Hello world"

    def test_only_marker(self):
        result = strip_tool_markers("[SEARCH: test]")
        assert result == ""
