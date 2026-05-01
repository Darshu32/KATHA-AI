"""Stage 5 — conversation recall tool.

When a chat session gets long, the agent's working context window
gets dominated by the latest few turns; older messages get summarised
out or truncated by the provider. This tool gives the agent a way to
*explicitly* re-fetch a slice of the persisted conversation when it
needs to refer back to something the user said earlier — a brief
detail, a constraint, an earlier dimension.

Why a tool, not the system prompt
---------------------------------
Putting the entire chat history into every system prompt would burn
tokens on every turn. Instead we let the model decide when it
actually needs older content, and serve only the slice it asks for.

Read-only — no audit footprint, no state mutation. Project-scope
guard: the tool refuses to run without ``ctx.session_id`` (it has no
notion of "current chat" without that).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.persistence import _row_to_agent_message  # noqa: F401  (used in tests)
from app.agents.tool import ToolContext, ToolError, tool
from app.repositories.chat_history import ChatHistoryRepository


class RecallRecentChatInput(BaseModel):
    """LLM input for the conversation-recall tool."""

    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description=(
            "How many of the most-recent persisted messages to return. "
            "Default 10. Capped at 50 to keep token cost predictable."
        ),
    )
    role_filter: Optional[str] = Field(
        default=None,
        description=(
            "Optional role filter — 'user', 'assistant', or 'tool'. "
            "Use 'user' to recall only what the architect said; useful "
            "when re-checking a constraint without re-reading every "
            "tool call."
        ),
    )


class RecalledMessage(BaseModel):
    position: int
    role: str
    text_preview: str
    tool_call_count: int = 0
    created_at: Optional[str] = None


class RecallRecentChatOutput(BaseModel):
    session_id: str
    total_messages: int
    returned_count: int
    messages: list[RecalledMessage] = Field(
        description="Newest-first list of message previews.",
    )


@tool(
    name="recall_recent_chat",
    description=(
        "Re-fetch a slice of the persisted conversation history for "
        "the current chat session. Use when the user references "
        "something said earlier ('what did I say about the budget?', "
        "'go back to the dimensions we discussed') and the working "
        "context might not have it. Read-only. Returns text previews "
        "rather than full content to keep token cost predictable. "
        "Requires an active chat session in scope."
    ),
    timeout_seconds=30.0,
)
async def recall_recent_chat(
    ctx: ToolContext,
    input: RecallRecentChatInput,
) -> RecallRecentChatOutput:
    if not ctx.session_id:
        raise ToolError(
            "No chat session in scope. The recall tool only works "
            "inside a persisted chat — ensure session_id is set on "
            "the agent context."
        )

    rows = await ChatHistoryRepository.list_messages(
        ctx.session,
        session_id=ctx.session_id,
        limit=input.limit if input.role_filter is None else None,
        oldest_first=False,
    )

    # Apply role filter post-fetch — the role index isn't dense enough
    # to push down at the DB layer for this volume.
    if input.role_filter:
        wanted = input.role_filter.lower()
        rows = [r for r in rows if (r.role or "").lower() == wanted]
        rows = rows[: input.limit]

    total = await ChatHistoryRepository.count_messages(ctx.session, ctx.session_id)

    out: list[RecalledMessage] = []
    for r in rows:
        created = getattr(r, "created_at", None)
        out.append(
            RecalledMessage(
                position=int(r.position),
                role=str(r.role or ""),
                text_preview=str(r.text_preview or "")[:500],
                tool_call_count=int(r.tool_call_count or 0),
                created_at=(
                    created.isoformat() if hasattr(created, "isoformat") else None
                ),
            )
        )

    return RecallRecentChatOutput(
        session_id=ctx.session_id,
        total_messages=total,
        returned_count=len(out),
        messages=out,
    )
