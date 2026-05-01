"""Stage 5 — bridge between persisted ChatMessage rows and runtime types.

The agent runtime speaks :class:`AgentMessage` (Anthropic-shaped
content blocks); the DB stores :class:`ChatMessage` (a JSONB content
column + flat denormalised previews). This module is the only place
those two shapes meet.

Three operations:

- :func:`load_history` — read an entire session's persisted messages
  and reconstruct the runtime ``AgentMessage`` list the agent loop
  expects. Reads sequentially in ``position`` order.
- :func:`persist_user_turn` — write the user's input before iteration
  begins. Captures it even if the agent loop crashes mid-iteration.
- :func:`persist_assistant_turn` — write one assistant turn (text +
  tool_call blocks) plus a separate ``tool`` row carrying the
  results, so the UI can render each tool card inline.

The persisted ``content`` JSONB shape mirrors the runtime types:

    {"type": "text", "text": "..."}                        # role=user
    {"type": "assistant",                                  # role=assistant
     "blocks": [
       {"kind": "text", "text": "..."},
       {"kind": "tool_call", "id": "...", "name": "...", "input": {...}},
     ]}
    {"type": "tool_results",                               # role=tool
     "results": [
       {"tool_call_id": "...", "name": "...", "ok": true,
        "output": {...}, "error": null, "elapsed_ms": 12.3},
     ]}

Why one row per assistant turn (not one per block)
--------------------------------------------------
Anthropic counts a turn as a single message regardless of how many
content blocks it contains. Splitting blocks across DB rows would
break the 1:1 mapping with provider turns and complicate replay.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import (
    AgentMessage,
    TextContent,
    ToolCallContent,
    ToolResultContent,
)
from app.models.orm import ChatMessage
from app.repositories.chat_history import ChatHistoryRepository

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# DB → runtime
# ─────────────────────────────────────────────────────────────────────


def _row_to_agent_message(row: ChatMessage) -> Optional[AgentMessage]:
    """Translate one persisted row into a runtime AgentMessage.

    Returns ``None`` when the row is unsalvageable (corrupt content,
    unknown role) — the caller filters those out. We log + skip
    instead of raising so a single bad row can't block resumption of
    a 200-message conversation.
    """
    content = row.content or {}
    role = (row.role or "").lower()

    try:
        if role == "user":
            text = str(content.get("text") or "")
            return AgentMessage(role="user", content=text)

        if role == "assistant":
            blocks: list[Any] = []
            for raw in content.get("blocks") or []:
                kind = (raw or {}).get("kind")
                if kind == "text":
                    blocks.append(TextContent(text=str(raw.get("text") or "")))
                elif kind == "tool_call":
                    blocks.append(
                        ToolCallContent(
                            id=str(raw.get("id") or ""),
                            name=str(raw.get("name") or ""),
                            input=dict(raw.get("input") or {}),
                        )
                    )
            if not blocks:
                # Empty assistant turn — fall back to text_preview.
                blocks.append(TextContent(text=row.text_preview or ""))
            return AgentMessage(role="assistant", content=blocks)

        if role == "tool":
            results = []
            for raw in content.get("results") or []:
                results.append(
                    ToolResultContent(
                        tool_call_id=str(raw.get("tool_call_id") or ""),
                        output=raw.get("output") if raw.get("ok") else raw.get("error"),
                        is_error=not bool(raw.get("ok", True)),
                    )
                )
            if not results:
                return None
            return AgentMessage(role="user", content=results)
    except Exception:  # noqa: BLE001
        log.warning("chat_message %s could not be replayed", row.id)
        return None

    return None


async def load_history(
    db: AsyncSession,
    *,
    session_id: str,
    limit: Optional[int] = None,
) -> list[AgentMessage]:
    """Load a session's persisted messages, oldest-first, as runtime types.

    ``limit`` slices the query to the most recent N messages but still
    returns them oldest-first — useful for very long conversations
    where we want context but not unbounded.
    """
    if limit is not None:
        # Pull the last N rows newest-first, then reverse so the
        # agent sees them oldest-first.
        rows = await ChatHistoryRepository.list_messages(
            db, session_id=session_id, limit=limit, oldest_first=False,
        )
        rows = list(reversed(rows))
    else:
        rows = await ChatHistoryRepository.list_messages(
            db, session_id=session_id, oldest_first=True,
        )

    out: list[AgentMessage] = []
    for row in rows:
        msg = _row_to_agent_message(row)
        if msg is not None:
            out.append(msg)
    return out


# ─────────────────────────────────────────────────────────────────────
# Runtime → DB
# ─────────────────────────────────────────────────────────────────────


async def persist_user_turn(
    db: AsyncSession,
    *,
    session_id: str,
    text: str,
) -> ChatMessage:
    """Append a ``user`` row carrying the architect's input."""
    return await ChatHistoryRepository.append_message(
        db,
        session_id=session_id,
        role="user",
        content={"type": "text", "text": text},
        text_preview=text[:200],
    )


async def persist_assistant_turn(
    db: AsyncSession,
    *,
    session_id: str,
    message: AgentMessage,
    elapsed_ms: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> ChatMessage:
    """Append an ``assistant`` row carrying text + tool_call blocks.

    The runtime ``AgentMessage`` for an assistant turn has
    ``content`` = list of TextContent and/or ToolCallContent. We
    serialise both so a future load can fully replay the turn.
    """
    blocks: list[dict[str, Any]] = []
    text_preview_parts: list[str] = []
    tool_call_count = 0

    for block in (message.content or []):  # type: ignore[union-attr]
        if isinstance(block, TextContent):
            blocks.append({"kind": "text", "text": block.text})
            text_preview_parts.append(block.text)
        elif isinstance(block, ToolCallContent):
            blocks.append(
                {
                    "kind": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
            tool_call_count += 1
            # Brief mention in the preview so the chat list shows what happened.
            text_preview_parts.append(f"[tool: {block.name}]")

    return await ChatHistoryRepository.append_message(
        db,
        session_id=session_id,
        role="assistant",
        content={"type": "assistant", "blocks": blocks},
        text_preview=" ".join(text_preview_parts)[:2000],
        tool_call_count=tool_call_count,
        elapsed_ms=elapsed_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def persist_tool_results(
    db: AsyncSession,
    *,
    session_id: str,
    results: list[dict[str, Any]],
) -> ChatMessage:
    """Append a ``tool`` row carrying the results of one batch of tool calls.

    ``results`` shape (one dict per tool call):

        {"tool_call_id": str, "name": str, "ok": bool,
         "output": dict | None, "error": dict | None,
         "elapsed_ms": float}

    The agent loop hands us this list verbatim once it's run all the
    tool calls in one iteration.
    """
    total_elapsed = sum(float(r.get("elapsed_ms") or 0.0) for r in results)
    preview_parts: list[str] = []
    for r in results:
        ok = r.get("ok")
        name = r.get("name") or "?"
        if ok:
            preview_parts.append(f"{name}: ok")
        else:
            err = (r.get("error") or {}).get("type") or "error"
            preview_parts.append(f"{name}: {err}")

    return await ChatHistoryRepository.append_message(
        db,
        session_id=session_id,
        role="tool",
        content={"type": "tool_results", "results": results},
        text_preview=" | ".join(preview_parts)[:2000],
        tool_call_count=len(results),
        elapsed_ms=total_elapsed,
    )
