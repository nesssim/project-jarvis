from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from tools.registry import ToolNotFoundError, ToolRegistry

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ExecuteRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    params: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=5, ge=1, le=20)


@router.post("/execute")
async def execute_tool(request: Request, body: ExecuteRequest) -> dict:
    registry: ToolRegistry = request.app.state.tool_registry
    try:
        result = await registry.execute(body.tool, body.params)
        return {"result": result}
    except ToolNotFoundError as e:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=404,
            content={"error": str(e)},
        )


@router.get("/list")
async def list_tools(request: Request) -> dict:
    registry: ToolRegistry = request.app.state.tool_registry
    return {"tools": registry.list_tools()}


@router.post("/search")
async def search(request: Request, body: SearchRequest) -> dict:
    from tools.search import web_search

    return await web_search(body.query, body.max_results)
