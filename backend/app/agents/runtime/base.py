"""Provider-agnostic types for the agent runtime.

Why these types exist
---------------------
Anthropic and OpenAI use different message shapes, different tool
formats, and different streaming events. Coding both into the agent
loop would double our maintenance load. Instead the **agent loop
speaks only the types in this module**, and each provider
implementation does the translation.

The translation is one-way per direction:
  - Outgoing: ``AgentMessage`` list → provider's native chat format.
  - Incoming: provider's stream events → ``ProviderEvent`` instances.

Anthropic's tool-use protocol is the closer match to what we want, so
the abstraction leans Anthropic-shaped (content blocks, tool_use IDs,
etc). OpenAI's slightly different model is mapped onto it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

# ─────────────────────────────────────────────────────────────────────
# Content blocks (Anthropic-style: a message is a list of blocks)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class TextContent:
    """Plain-text block — both directions (input + output)."""

    text: str


@dataclass
class ToolCallContent:
    """Assistant requested a tool. Output direction only."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultContent:
    """User-side reply to a tool_call. Input direction only."""

    tool_call_id: str
    output: Any
    is_error: bool = False


AssistantContent = Union[TextContent, ToolCallContent]
"""Anything an assistant turn can contain."""


# ─────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────


@dataclass
class AgentMessage:
    """One conversation turn, provider-agnostic.

    - Role ``user`` carries either plain text or a list of
      :class:`ToolResultContent` (when answering a previous tool call).
    - Role ``assistant`` carries a list of :class:`AssistantContent`
      (text and/or tool calls).
    - Role ``system`` is single-string; we accept it for clarity but
      most providers prefer a separate system parameter (handled in
      provider impls).
    """

    role: Literal["user", "assistant", "system"]
    content: Union[str, list[AssistantContent], list[ToolResultContent]]


# ─────────────────────────────────────────────────────────────────────
# Streaming events (provider → agent loop)
# ─────────────────────────────────────────────────────────────────────


StopReason = Literal[
    "end_turn",       # assistant finished a normal text turn
    "tool_use",       # assistant requested tool calls — loop again
    "max_tokens",     # stopped because we hit token cap
    "error",          # provider error
]


@dataclass
class UsageStats:
    """Token usage for one assistant turn."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ProviderEvent:
    """Single event emitted while the assistant is composing a turn.

    Event type is implicit by which fields are populated:

    - ``text_delta``    : ``text`` is the next chunk of plain text.
    - ``tool_call``     : ``tool_call`` is a complete (non-partial) call.
    - ``message_done``  : ``stop_reason`` + ``message`` populated; this
                           is the assembled assistant turn for replay
                           into the next iteration.
    - ``error``         : ``error`` populated.
    """

    type: Literal["text_delta", "tool_call", "message_done", "error"]
    text: Optional[str] = None
    tool_call: Optional[ToolCallContent] = None
    message: Optional[AgentMessage] = None
    stop_reason: Optional[StopReason] = None
    usage: Optional[UsageStats] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ProviderConfig:
    """Configuration the provider needs to make a call.

    Tool definitions are passed *here*, not in each call, so they can
    be cached on the provider side (Anthropic prompt caching).
    """

    model: str
    api_key: str
    system_prompt: str
    tools: list[dict[str, Any]]
    max_tokens: int = 2048
    temperature: float = 0.2
    base_url: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# Provider ABC
# ─────────────────────────────────────────────────────────────────────


class AgentProvider(ABC):
    """Async, streaming, tool-use-aware LLM provider."""

    name: str = "abstract"

    @abstractmethod
    async def stream(
        self,
        messages: list[AgentMessage],
        config: ProviderConfig,
    ) -> AsyncIterator[ProviderEvent]:
        """Send the conversation, stream events back.

        The provider must:

        1. Translate ``messages`` into its native chat format.
        2. Pass ``config.tools`` as the tool definitions.
        3. Stream provider events, ending with exactly one
           ``message_done`` event whose ``stop_reason`` tells the agent
           loop whether to iterate again.

        On error the provider must yield an ``error`` event and stop;
        it must not raise into the loop.
        """
        ...
