from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from memory.store import MemoryStore

router = APIRouter(prefix="/api/memory", tags=["memory"])


class StoreTurnRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)


class RecallRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=5, ge=1, le=50)


@router.post("/turns", status_code=201)
async def store_turn(request: Request, body: StoreTurnRequest) -> dict:
    store: MemoryStore = request.app.state.memory_store
    turn_id = await store.store_turn(body.session_id, body.role, body.content)
    return {"turn_id": turn_id}


@router.get("/turns/{session_id}")
async def get_recent_turns(request: Request, session_id: str, limit: int = 20) -> dict:
    store: MemoryStore = request.app.state.memory_store
    turns = await store.get_recent(session_id, limit)
    return {"turns": turns}


@router.post("/recall")
async def recall_memories(request: Request, body: RecallRequest) -> dict:
    store: MemoryStore = request.app.state.memory_store
    results = await store.recall(body.session_id, body.query, body.max_results)
    return {"memories": results}


@router.delete("/turns/{session_id}")
async def clear_session(request: Request, session_id: str) -> dict:
    store: MemoryStore = request.app.state.memory_store
    await store.clear_session(session_id)
    return {"deleted": True}
