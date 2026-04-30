"""KATHA agent layer (Stage 2+).

The agent layer is what turns KATHA from a rigid pipeline into a true
"Claude for Architects" — an LLM that decides when to call tools, asks
clarifying questions, cites its sources, and reasons in the open.

Stage 2 ships:
  - The tool framework (``app.agents.tool``)
  - A provider abstraction (Anthropic primary, OpenAI fallback)
  - The architect agent loop
  - One real tool: ``estimate_project_cost`` (Stage 1 cost engine
    wrapped as an LLM-callable function)

Later stages add more tools (Stage 4), multi-modal inputs (Stage 7),
RAG (Stage 6), and persistent memory (Stage 8).

Public surface
--------------
- :func:`tool` — decorator that registers an async function as a tool
- :class:`ToolContext` — request-scoped state passed to every tool
- :class:`ToolRegistry` — list / lookup / call by name
- :func:`run_architect_agent` — main agent loop entry point
- :class:`AgentEvent` — SSE event protocol
"""

from app.agents.stream import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    StreamFormatter,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.agents.tool import ToolContext, ToolRegistry, ToolSpec, tool

__all__ = [
    "AgentEvent",
    "DoneEvent",
    "ErrorEvent",
    "StreamFormatter",
    "TextEvent",
    "ThinkingEvent",
    "ToolCallEvent",
    "ToolContext",
    "ToolRegistry",
    "ToolResultEvent",
    "ToolSpec",
    "tool",
]
