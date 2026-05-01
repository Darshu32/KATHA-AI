"""SSE event protocol for the agent loop.

The agent loop emits a stream of high-level events that are *more*
structured than provider deltas — they're what the frontend (Stage 13
UI work) actually needs to render.

Event vocabulary
----------------

==================== =========================================================
Event                Payload
==================== =========================================================
``session``          ``{ "id", "new", "project_id" }`` — Stage-5 session id
                       resolved server-side. Emitted as the first SSE event so
                       the client can store it for resumption. ``new=true``
                       indicates the server auto-created the session.
``thinking``         ``{ "text": "..." }`` — provider's text deltas before any
                       tool call. Frontend can use this for "Claude is
                       thinking…" indicators.
``tool_call``        ``{ "id", "name", "input" }`` — agent decided to invoke a
                       tool. Show as a chip in the chat thread.
``tool_result``      ``{ "id", "name", "ok", "output", "error", "elapsed_ms" }``
                       — outcome of one tool. Failures don't end the stream;
                       the agent recovers in the next iteration.
``text``             ``{ "text": "..." }`` — final assistant text after all
                       tool calls. Same shape as ``thinking``; frontend
                       distinguishes by event name.
``done``             ``{ "stop_reason", "usage", "iterations" }`` — terminal.
``error``            ``{ "message": "..." }`` — provider or loop error.
==================== =========================================================

The wire format is **SSE** (``text/event-stream``):

::

    event: tool_call
    data: {"id":"...","name":"estimate_project_cost","input":{...}}

    event: tool_result
    data: {"id":"...","ok":true,"output":{...},"elapsed_ms":1240.5}

    event: done
    data: {"stop_reason":"end_turn","usage":{"input_tokens":1232,"output_tokens":348},"iterations":2}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

EventName = Literal[
    "session", "thinking", "tool_call", "tool_result", "text", "done", "error",
]


# ─────────────────────────────────────────────────────────────────────
# Event dataclasses
# ─────────────────────────────────────────────────────────────────────


@dataclass
class AgentEvent:
    """Base — every concrete event subclasses this."""

    event: EventName

    def payload(self) -> dict[str, Any]:
        """JSON payload for the SSE ``data:`` line."""
        d = asdict(self)
        d.pop("event", None)
        return d


@dataclass
class SessionEvent(AgentEvent):
    """First SSE event when ``/v2/chat`` resolves or creates a session.

    The frontend stores ``id`` and replays it on the next turn so the
    server can load history from DB. ``new`` distinguishes "this is
    your first message in this session" from "we resumed your existing
    session".
    """
    id: str = ""
    new: bool = False
    project_id: Optional[str] = None
    event: EventName = "session"


@dataclass
class ThinkingEvent(AgentEvent):
    text: str = ""
    event: EventName = "thinking"


@dataclass
class ToolCallEvent(AgentEvent):
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    event: EventName = "tool_call"


@dataclass
class ToolResultEvent(AgentEvent):
    id: str = ""
    name: str = ""
    ok: bool = True
    output: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    elapsed_ms: float = 0.0
    event: EventName = "tool_result"


@dataclass
class TextEvent(AgentEvent):
    text: str = ""
    event: EventName = "text"


@dataclass
class DoneEvent(AgentEvent):
    stop_reason: str = "end_turn"
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    event: EventName = "done"


@dataclass
class ErrorEvent(AgentEvent):
    message: str = ""
    event: EventName = "error"


# ─────────────────────────────────────────────────────────────────────
# Wire format
# ─────────────────────────────────────────────────────────────────────


class StreamFormatter:
    """Encode :class:`AgentEvent` instances onto an SSE stream.

    Strict SSE: ``event:`` and ``data:`` separated by ``\\n``, each
    record terminated by a blank line.
    """

    @staticmethod
    def encode(event: AgentEvent) -> bytes:
        payload = json.dumps(event.payload(), default=str, ensure_ascii=False)
        return (
            f"event: {event.event}\n"
            f"data: {payload}\n\n"
        ).encode("utf-8")

    @staticmethod
    def comment(text: str) -> bytes:
        """SSE comment — used for keep-alives. Frontend ignores."""
        return f": {text}\n\n".encode("utf-8")
