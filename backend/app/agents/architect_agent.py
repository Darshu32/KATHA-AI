"""The KATHA architect agent — main entry point.

The loop in plain English
-------------------------
1. Hand the conversation + tool catalogue to the provider.
2. Stream what the assistant produces:
   - Text deltas → ``thinking`` / ``text`` events for the UI.
   - Tool calls → invoke the tool via the registry, emit ``tool_call``
     and ``tool_result`` events, append both to the conversation.
3. If the assistant ended with ``stop_reason == "tool_use"``, loop
   again (the assistant has tool results to read). Else we're done.
4. Cap iterations to avoid infinite loops. Cap total tokens via the
   provider's ``max_tokens``.

The loop yields :class:`AgentEvent` instances which the route layer
serializes to SSE. Anything that doesn't fit an event type (provider
errors, validation failures) becomes an ``error`` event and the loop
terminates.

What this loop is NOT (yet)
---------------------------
- No DB-backed memory. Conversation is request-scoped; Stage 8 adds
  cross-session memory.
- No parallel tool dispatch. Tools run sequentially. Stage 5 may
  parallelise independent tool calls.
- No automatic re-tries. If the provider errors, we surface it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Optional

from app.agents.prompts import ARCHITECT_SYSTEM_PROMPT
from app.agents.runtime import (
    AgentMessage,
    AgentProvider,
    ProviderConfig,
    TextContent,
    ToolCallContent,
    ToolResultContent,
    get_provider,
)
from app.agents.stream import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.agents.tool import REGISTRY, ToolContext, call_tool
from app.agents.tools import ensure_tools_registered
from app.config import get_settings

log = logging.getLogger(__name__)


# Hard caps so a misbehaving model can't burn budget unbounded.
MAX_ITERATIONS = 8
MAX_TOOL_CALLS = 12


# Run-once on first import — populates REGISTRY with built-in tools.
ensure_tools_registered()


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


async def run_architect_agent(
    *,
    user_message: str,
    history: Optional[list[AgentMessage]] = None,
    ctx: ToolContext,
    provider: Optional[AgentProvider] = None,
    system_prompt: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> AsyncIterator[AgentEvent]:
    """Run one architect turn against the LLM, streaming agent events.

    Parameters
    ----------
    user_message:
        Latest user input. Appended to ``history`` automatically.
    history:
        Previous conversation turns (provider-agnostic
        :class:`AgentMessage`). Use ``[]`` for a fresh conversation.
    ctx:
        Request-scoped state passed to every tool. Caller owns the DB
        session and is responsible for committing on success.
    provider:
        Override the default (Anthropic). Only useful for tests.
    system_prompt:
        Override the architect prompt. Useful for tests + future
        per-project / per-architect customisation.
    max_tokens / temperature:
        Per-call provider knobs.

    Yields
    ------
    :class:`AgentEvent` — one per provider delta or tool result.
    """
    settings = get_settings()
    provider = provider or get_provider()

    if not settings.has_anthropic_key and provider.name == "anthropic":
        yield ErrorEvent(
            message=(
                "ANTHROPIC_API_KEY is not configured. The agent loop "
                "requires a live LLM call; set the env var to enable it."
            )
        )
        return

    # Build the running conversation.
    messages: list[AgentMessage] = list(history or [])
    messages.append(AgentMessage(role="user", content=user_message))

    config = ProviderConfig(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        system_prompt=system_prompt or ARCHITECT_SYSTEM_PROMPT,
        tools=REGISTRY.definitions_for_llm(),
        max_tokens=max_tokens,
        temperature=temperature,
    )

    iteration = 0
    tool_calls_made = 0
    total_input_tokens = 0
    total_output_tokens = 0
    final_stop_reason = "end_turn"

    while iteration < MAX_ITERATIONS:
        iteration += 1
        log.debug("agent.iteration %d", iteration)

        # Per-iteration buffer — text *before* any tool call counts as
        # "thinking", text *after* is the final assistant answer.
        seen_tool_call_this_iteration = False
        assistant_message: Optional[AgentMessage] = None

        async for prov_event in provider.stream(messages, config):
            if prov_event.type == "text_delta":
                if seen_tool_call_this_iteration:
                    yield TextEvent(text=prov_event.text or "")
                else:
                    yield ThinkingEvent(text=prov_event.text or "")

            elif prov_event.type == "tool_call":
                seen_tool_call_this_iteration = True
                tc = prov_event.tool_call
                if tc is None:
                    continue
                yield ToolCallEvent(id=tc.id, name=tc.name, input=tc.input)

            elif prov_event.type == "message_done":
                assistant_message = prov_event.message
                final_stop_reason = prov_event.stop_reason or "end_turn"
                if prov_event.usage:
                    total_input_tokens += prov_event.usage.input_tokens
                    total_output_tokens += prov_event.usage.output_tokens
                break

            elif prov_event.type == "error":
                yield ErrorEvent(message=prov_event.error or "provider error")
                return

        if assistant_message is None:
            yield ErrorEvent(message="provider stream ended without message_done")
            return

        # Append assistant turn — needed both for the tool-result reply
        # below and for the final transcript on the client.
        messages.append(assistant_message)

        # Was this an end-turn or a tool-use turn?
        tool_calls = [
            c for c in (assistant_message.content or [])  # type: ignore[union-attr]
            if isinstance(c, ToolCallContent)
        ]
        if not tool_calls or final_stop_reason != "tool_use":
            # Plain text reply — emit text deltas already happened, we're done.
            break

        # Run tools sequentially, append a single user message
        # carrying every tool result — Anthropic expects one
        # ``user`` turn with N ``tool_result`` blocks.
        tool_result_blocks: list[ToolResultContent] = []
        for tc in tool_calls:
            tool_calls_made += 1
            if tool_calls_made > MAX_TOOL_CALLS:
                yield ErrorEvent(
                    message=f"agent exceeded MAX_TOOL_CALLS={MAX_TOOL_CALLS}"
                )
                return

            result = await call_tool(tc.name, tc.input, ctx)

            yield ToolResultEvent(
                id=tc.id,
                name=tc.name,
                ok=bool(result.get("ok")),
                output=result.get("output"),
                error=result.get("error"),
                elapsed_ms=float(result.get("elapsed_ms") or 0.0),
            )

            tool_result_blocks.append(
                ToolResultContent(
                    tool_call_id=tc.id,
                    output=(
                        result.get("output")
                        if result.get("ok")
                        else result.get("error")
                    ),
                    is_error=not result.get("ok"),
                )
            )

        messages.append(AgentMessage(role="user", content=tool_result_blocks))
        # Loop again — the assistant now has tool results to read.

    yield DoneEvent(
        stop_reason=final_stop_reason,
        iterations=iteration,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers for callers
# ─────────────────────────────────────────────────────────────────────


def history_from_dicts(items: list[dict[str, str]]) -> list[AgentMessage]:
    """Convert a [{role, content}] list into :class:`AgentMessage` instances.

    Convenience for the route handler — accepts the same shape the
    legacy ``/chat`` endpoint uses.
    """
    out: list[AgentMessage] = []
    for item in items:
        role = item.get("role") or "user"
        content = item.get("content") or ""
        if role not in {"user", "assistant", "system"}:
            continue
        if role == "assistant":
            out.append(AgentMessage(role="assistant", content=[TextContent(text=content)]))
        else:
            out.append(AgentMessage(role=role, content=content))  # type: ignore[arg-type]
    return out
