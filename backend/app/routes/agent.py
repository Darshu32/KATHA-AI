"""Stage 2 agent route — ``POST /v2/chat`` with SSE streaming.

Why ``/v2/chat`` (not ``/chat``)
-------------------------------
The legacy ``/chat`` endpoint is a single-shot Q&A streamer backed by
``app.services.chat_engine``. It's still used by the existing UI.
``/v2/chat`` is the new agentic surface — it understands tool calls,
streams reasoning, and returns provenance for every cited number.

Both coexist until Stage 13 retires the old one.

SSE event protocol
------------------
See :mod:`app.agents.stream` for the full vocabulary. Frontend should
treat any unknown event name as informational (ignore safely).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.architect_agent import history_from_dicts, run_architect_agent
from app.agents.stream import ErrorEvent, StreamFormatter
from app.agents.tool import ToolContext
from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.observability.request_id import get_request_id

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["agent"])


# ─────────────────────────────────────────────────────────────────────
# Request body
# ─────────────────────────────────────────────────────────────────────


class _ChatMessageInput(BaseModel):
    role: str = Field(description="user | assistant")
    content: str = Field(min_length=1)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    history: list[_ChatMessageInput] = Field(
        default_factory=list,
        description="Previous turns. Caller supplies; Stage 8 will load from DB.",
    )
    project_id: str | None = Field(default=None, max_length=64)


# ─────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────


@router.post("/chat")
async def agent_chat(
    body: AgentChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a Stage-2 agent turn as SSE.

    The agent loop:
      - Sees the user message + history
      - May call tools (Stage 2: just ``estimate_project_cost``)
      - Streams ``thinking``, ``tool_call``, ``tool_result``, ``text``,
        and finally ``done`` events
      - Records pricing snapshots + audit events as side-effects

    Errors during the loop become ``error`` SSE events (the HTTP status
    is still 200 — clients should look at the event type).
    """
    history = history_from_dicts([m.model_dump() for m in body.history])

    ctx = ToolContext(
        session=db,
        actor_id=user.id,
        project_id=body.project_id,
        request_id=get_request_id(),
    )

    async def event_stream():
        try:
            async for event in run_architect_agent(
                user_message=body.message,
                history=history,
                ctx=ctx,
            ):
                if await request.is_disconnected():
                    log.info("client disconnected mid-agent-stream")
                    break
                yield StreamFormatter.encode(event)
        except Exception as exc:  # noqa: BLE001 — surface unexpected errors as SSE
            log.exception("agent stream crashed")
            yield StreamFormatter.encode(
                ErrorEvent(message=f"{type(exc).__name__}: {exc}")
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Tool catalogue (debug / introspection)
# ─────────────────────────────────────────────────────────────────────


@router.get("/tools")
async def list_tools(_: User = Depends(get_current_user)) -> dict:
    """Return the tool catalogue the agent currently has access to.

    Useful for the UI to render "what can the agent do?" lists, and for
    operators to verify Stage 4 tool registrations are wired correctly.
    """
    from app.agents.tool import REGISTRY

    return {
        "tools": REGISTRY.definitions_for_llm(),
        "count": len(REGISTRY.names()),
    }


# Also expose under HTTPException for unknown / error cases — the SSE
# endpoint never raises HTTPException itself; this is here for future
# REST-style endpoints layered onto /v2/.
def _maybe_400(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ErrorResponse(error="bad_input", message=reason).model_dump(),
    )
