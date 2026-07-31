from __future__ import annotations

import pytest
from tools.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry


async def _dummy_handler(query: str, max_results: int = 5) -> dict:
    return {"results": [{"title": "test", "url": "https://example.com", "snippet": "test"}]}


async def _failing_handler() -> None:
    msg = "something went wrong"
    raise ToolExecutionError(msg)


@pytest.fixture
def registry():
    r = ToolRegistry()
    r.register("web_search", "Search the web", _dummy_handler, {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    })
    return r


class TestToolRegistry:
    async def test_register_and_list(self, registry):
        tools = registry.list_tools()
        names = [t["name"] for t in tools]
        assert "web_search" in names

    async def test_execute(self, registry):
        result = await registry.execute("web_search", {"query": "test"})
        assert "results" in result
        assert len(result["results"]) == 1

    async def test_execute_not_found(self, registry):
        with pytest.raises(ToolNotFoundError):
            await registry.execute("nonexistent")

    async def test_execute_with_params(self, registry):
        result = await registry.execute("web_search", {"query": "test"})
        assert "results" in result

    async def test_execute_handler_error(self, registry):
        registry.register("failing", "Fails", _failing_handler)
        with pytest.raises(ToolExecutionError):
            await registry.execute("failing")

    async def test_get_tool(self, registry):
        info = registry.get_tool("web_search")
        assert info is not None
        assert info.name == "web_search"
        assert info.description == "Search the web"

    async def test_get_tool_not_found(self, registry):
        assert registry.get_tool("nonexistent") is None
