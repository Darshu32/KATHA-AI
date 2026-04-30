"""Provider abstraction for the agent runtime.

KATHA's agent loop must run against either:
  - **Anthropic Claude** (primary — best tool use + long context)
  - **OpenAI GPT** (fallback — cheaper, also for embeddings + legacy)

Rather than coding two agent loops, we collapse the differences in
this layer. Both providers produce the same internal event stream
(``ProviderEvent``) which the agent loop consumes.

Public surface
--------------
- :class:`AgentMessage` — provider-agnostic chat turn
- :class:`ProviderEvent` — the streaming event from the provider
- :class:`AgentProvider` — abstract base
- :func:`get_provider` — pick provider based on settings + availability
"""

from app.agents.runtime.base import (
    AgentMessage,
    AgentProvider,
    AssistantContent,
    ProviderConfig,
    ProviderEvent,
    StopReason,
    TextContent,
    ToolCallContent,
    ToolResultContent,
    UsageStats,
)
from app.agents.runtime.factory import get_provider

__all__ = [
    "AgentMessage",
    "AgentProvider",
    "AssistantContent",
    "ProviderConfig",
    "ProviderEvent",
    "StopReason",
    "TextContent",
    "ToolCallContent",
    "ToolResultContent",
    "UsageStats",
    "get_provider",
]
