from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from shared.logging import get_logger

logger = get_logger("tools.registry")

ToolHandler = Callable[..., Coroutine[Any, Any, Any]]

TIER_ORDER = ("safe", "confirm", "restricted")


def tool_tier_allowed(
    tool: str, safety_tiers: dict[str, list[str]], permitted_tier: str
) -> bool:
    tool_tier = next(
        (tier for tier, names in safety_tiers.items() if tool in names), None
    )
    if (
        tool_tier is None
        or tool_tier not in TIER_ORDER
        or permitted_tier not in TIER_ORDER
    ):
        return False
    return TIER_ORDER.index(tool_tier) <= TIER_ORDER.index(permitted_tier)


class ToolNotFoundError(Exception):
    pass


class ToolExecutionError(Exception):
    pass


class ToolInfo:
    def __init__(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters or {}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolInfo] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self._tools[name] = ToolInfo(name, description, handler, parameters)
        logger.info("tool registered", tool=name)

    def list_tools(self) -> list[dict]:
        return [info.to_dict() for info in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any] | None = None) -> Any:
        info = self._tools.get(name)
        if not info:
            raise ToolNotFoundError(f"Tool not found: {name}")
        params = params or {}
        try:
            return await info.handler(**params)
        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Tool '{name}' execution failed: {e}") from e

    def get_tool(self, name: str) -> ToolInfo | None:
        return self._tools.get(name)
