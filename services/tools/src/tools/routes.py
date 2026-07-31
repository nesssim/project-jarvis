from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tools.registry import ToolNotFoundError, ToolRegistry, tool_tier_allowed

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ExecuteRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    params: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=5, ge=1, le=20)


@router.post("/execute", response_model=None)
async def execute_tool(request: Request, body: ExecuteRequest) -> dict | JSONResponse:
    registry: ToolRegistry = request.app.state.tool_registry
    if registry.get_tool(body.tool) is None:
        return JSONResponse(
            status_code=404, content={"error": f"Tool not found: {body.tool}"}
        )
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return JSONResponse(
            status_code=503, content={"error": "Service configuration unavailable"}
        )
    safety = settings.tools
    if not tool_tier_allowed(
        body.tool, safety.safety_tiers, safety.safety_permitted_tier
    ):
        return JSONResponse(
            status_code=403,
            content={
                "error": (
                    f"Tool '{body.tool}' is not allowed under the current "
                    f"safety tier ('{safety.safety_permitted_tier}')"
                )
            },
        )
    try:
        result = await registry.execute(body.tool, body.params)
        return {"result": result}
    except ToolNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@router.get("/list")
async def list_tools(request: Request) -> dict:
    registry: ToolRegistry = request.app.state.tool_registry
    return {"tools": registry.list_tools()}


@router.post("/search")
async def search(request: Request, body: SearchRequest) -> dict:
    from tools.search import web_search

    return await web_search(body.query, body.max_results)
