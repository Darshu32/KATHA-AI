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

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.architect_agent import history_from_dicts, run_architect_agent
from app.agents.stream import ErrorEvent, SessionEvent, StreamFormatter
from app.agents.tool import ToolContext
from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.observability.request_id import get_request_id
from app.repositories.chat_history import ChatHistoryRepository

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
        description=(
            "Previous turns supplied by the caller. **Ignored when "
            "``session_id`` is set** — the server loads history from DB "
            "instead. Use only for stateless one-shots."
        ),
    )
    project_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional Stage-5 chat session id. When supplied, the agent "
            "loads history from ``chat_messages`` and persists every "
            "turn. When omitted, a new session is auto-created and its "
            "id is emitted as the first SSE event so the client can "
            "send it back on the next turn."
        ),
    )


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
    """Stream an agent turn as SSE.

    Stage 5 — session resumption
    ----------------------------
    - If ``session_id`` is supplied, the route resolves it against
      ``chat_sessions`` and confirms the requesting user owns it.
      Mismatches return ``404`` (we don't leak existence).
    - If ``session_id`` is omitted, a new ``chat_sessions`` row is
      created (scoped to ``project_id`` if provided) and its id is
      yielded as the first SSE event under the ``session`` event name.
    - The agent loop persists every assistant + tool turn against the
      resolved session.

    Errors during the loop become ``error`` SSE events (the HTTP
    status is still 200 — clients should look at the event type).
    """
    # Resolve / create the chat session.
    session_id = body.session_id
    new_session_created = False

    if session_id:
        chat = await ChatHistoryRepository.get_session_for_owner(
            db, session_id=session_id, owner_id=user.id,
        )
        if chat is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error="not_found",
                    message="Chat session not found for this user.",
                ).model_dump(),
            )
    else:
        chat = await ChatHistoryRepository.create_session(
            db,
            owner_id=user.id,
            project_id=body.project_id,
        )
        # Commit the session row immediately so the client gets a
        # stable id even if the agent loop crashes mid-stream.
        await db.commit()
        session_id = chat.id
        new_session_created = True

    # Client-supplied history is ignored when persistence is on.
    # Keep the conversion path for the (rare) stateless test mode.
    history = (
        []
        if session_id
        else history_from_dicts([m.model_dump() for m in body.history])
    )

    ctx = ToolContext(
        session=db,
        actor_id=user.id,
        project_id=body.project_id,
        session_id=session_id,
        request_id=get_request_id(),
    )

    async def event_stream():
        # Emit the resolved session id up-front so the client can
        # store it and resume on the next turn.
        yield StreamFormatter.encode(
            SessionEvent(
                id=session_id,
                new=new_session_created,
                project_id=body.project_id,
            )
        )

        try:
            async for event in run_architect_agent(
                user_message=body.message,
                history=history,
                ctx=ctx,
                session_id=session_id,
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
# Stage 5 — chat session listing + transcript access
# ─────────────────────────────────────────────────────────────────────


@router.get("/sessions")
async def list_chat_sessions(
    project_id: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List recent chat sessions for the authenticated user.

    Optionally filter by ``project_id``. Sessions are sorted
    newest-first by ``updated_at``. The response is slim — message
    previews live behind ``GET /v2/sessions/{id}/messages``.
    """
    sessions = await ChatHistoryRepository.list_sessions_for_owner(
        db, owner_id=user.id, project_id=project_id, limit=max(1, min(limit, 200)),
    )
    return {
        "count": len(sessions),
        "sessions": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "title": s.title,
                "status": s.status,
                "message_count": s.message_count,
                "last_message_at": s.last_message_at,
                "created_at": s.created_at.isoformat()
                if hasattr(s.created_at, "isoformat") else None,
                "updated_at": s.updated_at.isoformat()
                if hasattr(s.updated_at, "isoformat") else None,
            }
            for s in sessions
        ],
    }


@router.get("/sessions/{session_id}/messages")
async def get_chat_session_messages(
    session_id: str,
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the persisted messages for one session, oldest-first."""
    chat = await ChatHistoryRepository.get_session_for_owner(
        db, session_id=session_id, owner_id=user.id,
    )
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message="Chat session not found for this user.",
            ).model_dump(),
        )
    rows = await ChatHistoryRepository.list_messages(
        db, session_id=session_id, limit=max(1, min(limit, 1000)),
    )
    return {
        "session_id": session_id,
        "count": len(rows),
        "messages": [
            {
                "position": r.position,
                "role": r.role,
                "content": r.content,
                "text_preview": r.text_preview,
                "tool_call_count": r.tool_call_count,
                "elapsed_ms": r.elapsed_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "created_at": r.created_at.isoformat()
                if hasattr(r.created_at, "isoformat") else None,
            }
            for r in rows
        ],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_chat_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Archive a chat session. Idempotent."""
    chat = await ChatHistoryRepository.archive_session(
        db, session_id=session_id, owner_id=user.id,
    )
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message="Chat session not found for this user.",
            ).model_dump(),
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
