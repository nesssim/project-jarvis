from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from orchestrator.clients.llm import BaseLLMClient
from orchestrator.clients.memory import MemoryClient
from orchestrator.clients.tools import ToolsClient
from orchestrator.core.prompt import PromptManager
from orchestrator.core.tool_parser import parse_tool_calls, strip_tool_markers

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: str = Field(
        default="", description="Session ID for conversation continuity"
    )


def _format_memories(memories: list[dict]) -> str:
    if not memories:
        return "No relevant past conversations found."
    lines = ["Relevant past context:"]
    for m in memories:
        lines.append(f"- {m.get('content', '')}")
    return "\n".join(lines)


def _format_turns(turns: list[dict]) -> str:
    if not turns:
        return "No recent conversation history."
    lines = []
    for t in reversed(turns):
        role = t.get("role", "user")
        content = t.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    llm_client: BaseLLMClient = request.app.state.llm_client
    prompt_manager: PromptManager = request.app.state.prompt_manager
    memory_client: MemoryClient | None = getattr(
        request.app.state, "memory_client", None
    )
    tools_client: ToolsClient | None = getattr(request.app.state, "tools_client", None)

    session_id = body.session_id or uuid.uuid4().hex[:12]

    if memory_client:
        await memory_client.store_turn(session_id, "user", body.message)
        memories = await memory_client.recall(session_id, body.message, max_results=5)
        recent_turns = await memory_client.get_recent(session_id, limit=20)
    else:
        memories = []
        recent_turns = []

    system_prompt = prompt_manager.render(
        max_tokens=str(llm_client.config.generation.max_tokens),
        retrieved_memory=_format_memories(memories),
        short_term_buffer=_format_turns(recent_turns),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": body.message},
    ]

    full_response = ""
    clean_response = ""
    async for token in llm_client.generate(messages=messages):
        full_response += token

    if memory_client:
        clean_response = strip_tool_markers(full_response)
        if clean_response:
            await memory_client.store_turn(session_id, "assistant", clean_response)

    tool_calls = parse_tool_calls(full_response)

    async def event_stream():
        if not tool_calls:
            yield f"data: {clean_response}\n\n"
            yield "data: [DONE]\n\n"
            return

        for tc in tool_calls:
            if not tools_client:
                yield f"data: {clean_response}\n\n"
                yield "data: [DONE]\n\n"
                return

            result = await tools_client.execute(tc.tool, tc.params)

            follow_up_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": body.message},
                {"role": "assistant", "content": clean_response or full_response},
                {
                    "role": "system",
                    "content": (
                        f"Tool result from '{tc.tool}':\n{result}\n\n"
                        "Use this information to answer the user's question."
                    ),
                },
            ]

            follow_up = ""
            async for token in llm_client.generate(messages=follow_up_messages):
                follow_up += token
                yield f"data: {token}\n\n"

            if memory_client and follow_up.strip():
                await memory_client.store_turn(
                    session_id, "assistant", follow_up.strip()
                )

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
            "X-Session-ID": session_id,
        },
    )
