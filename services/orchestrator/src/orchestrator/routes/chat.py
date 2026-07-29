from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from orchestrator.clients.llm import BaseLLMClient
from orchestrator.core.prompt import PromptManager

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    llm_client: BaseLLMClient = request.app.state.llm_client
    prompt_manager: PromptManager = request.app.state.prompt_manager

    system_prompt = prompt_manager.render(
        max_tokens="512", retrieved_memory="", short_term_buffer=""
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": body.message},
    ]

    async def event_stream():
        async for token in llm_client.generate(messages=messages):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"},
    )
