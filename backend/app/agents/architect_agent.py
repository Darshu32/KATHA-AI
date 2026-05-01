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

Stage 5 additions
-----------------
- **DB-backed memory.** When ``session_id`` is supplied, history is
  loaded from the ``chat_messages`` table at the start of the turn
  and every assistant + tool batch is persisted as it happens. The
  client-supplied ``history`` is then ignored — only the DB is the
  source of truth (security: stops a malicious client rewriting the
  past to manipulate the agent).
- **Parallel tool dispatch.** Tool calls within a single iteration
  are split into "read-only" and "write" buckets. Read-only tools
  (``audit_target_type is None``) run concurrently via
  :func:`asyncio.gather`; write tools run sequentially because they
  share the AsyncSession (parallel writes on one session are unsafe
  in SQLAlchemy async).

What this loop is NOT (yet)
---------------------------
- No automatic re-tries on provider error. If the LLM errors, we
  surface it and stop.
- No RAG over project artefacts — that's Stage 5B.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Optional

from app.agents.persistence import (
    load_history,
    persist_assistant_turn,
    persist_tool_results,
    persist_user_turn,
)
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
    session_id: Optional[str] = None,
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
        **Ignored when** ``session_id`` is provided — DB-loaded
        history takes precedence.
    ctx:
        Request-scoped state passed to every tool. Caller owns the DB
        session and is responsible for committing on success.
    session_id:
        When supplied, the loop:

        - Loads history from ``chat_messages`` (overrides ``history``).
        - Persists the user input before iteration begins.
        - Persists each assistant turn + tool-result batch.

        When ``None``, persistence is disabled and ``history`` is used
        verbatim — useful for one-shot tests or stateless integrations.
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

    # Stage 5 — DB-backed memory.
    # When session_id is set, ignore client-supplied history and reload
    # from the persisted record. This stops a malicious client from
    # rewriting the past to manipulate the agent.
    if session_id is not None:
        messages: list[AgentMessage] = await load_history(
            ctx.session, session_id=session_id,
        )
        await persist_user_turn(
            ctx.session, session_id=session_id, text=user_message,
        )
    else:
        messages = list(history or [])

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
        # Token usage for *this* iteration only (so we can persist it
        # against the specific assistant row).
        iter_input_tokens = 0
        iter_output_tokens = 0

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
                    iter_input_tokens = prov_event.usage.input_tokens
                    iter_output_tokens = prov_event.usage.output_tokens
                    total_input_tokens += iter_input_tokens
                    total_output_tokens += iter_output_tokens
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

        # Persist the assistant turn (text + tool_call blocks).
        if session_id is not None:
            try:
                await persist_assistant_turn(
                    ctx.session,
                    session_id=session_id,
                    message=assistant_message,
                    input_tokens=iter_input_tokens,
                    output_tokens=iter_output_tokens,
                )
            except Exception as exc:  # noqa: BLE001 — never crash the loop on persist failure
                log.warning("chat persist (assistant) failed: %s", exc)

        # Was this an end-turn or a tool-use turn?
        tool_calls = [
            c for c in (assistant_message.content or [])  # type: ignore[union-attr]
            if isinstance(c, ToolCallContent)
        ]
        if not tool_calls or final_stop_reason != "tool_use":
            # Plain text reply — emit text deltas already happened, we're done.
            break

        if tool_calls_made + len(tool_calls) > MAX_TOOL_CALLS:
            yield ErrorEvent(
                message=f"agent exceeded MAX_TOOL_CALLS={MAX_TOOL_CALLS}"
            )
            return

        # Stage 5 — split read-only and write tool calls for safe
        # parallelisation. Tools without an audit_target_type are
        # read-only; they don't mutate the AsyncSession so it's safe
        # to run them concurrently. Write tools share the session,
        # so they must run serially (parallel writes on one
        # AsyncSession can lose updates and confuse SQLAlchemy).
        readonly_calls: list[ToolCallContent] = []
        write_calls: list[ToolCallContent] = []
        for tc in tool_calls:
            try:
                spec = REGISTRY.get(tc.name)
                if spec.audit_target_type is None:
                    readonly_calls.append(tc)
                else:
                    write_calls.append(tc)
            except Exception:  # unknown tool — handled by call_tool's envelope
                write_calls.append(tc)
        tool_calls_made += len(tool_calls)

        # Run read-only calls concurrently.
        readonly_results: list[dict] = []
        if readonly_calls:
            readonly_results = list(
                await asyncio.gather(
                    *(call_tool(tc.name, tc.input, ctx) for tc in readonly_calls)
                )
            )

        # Run write calls serially (one shared session).
        write_results: list[dict] = []
        for tc in write_calls:
            write_results.append(await call_tool(tc.name, tc.input, ctx))

        # Stitch results back into the original tool_calls order so the
        # provider sees its results in the order it asked for them.
        result_by_id: dict[str, dict] = {}
        for tc, res in zip(readonly_calls, readonly_results):
            result_by_id[tc.id] = (tc, res)  # type: ignore[assignment]
        for tc, res in zip(write_calls, write_results):
            result_by_id[tc.id] = (tc, res)  # type: ignore[assignment]

        tool_result_blocks: list[ToolResultContent] = []
        persisted_results: list[dict] = []
        for tc in tool_calls:
            _, result = result_by_id[tc.id]  # type: ignore[misc]
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
            persisted_results.append(
                {
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "ok": bool(result.get("ok")),
                    "output": result.get("output"),
                    "error": result.get("error"),
                    "elapsed_ms": float(result.get("elapsed_ms") or 0.0),
                }
            )

        # Persist the tool batch as one ``tool`` row.
        if session_id is not None and persisted_results:
            try:
                await persist_tool_results(
                    ctx.session,
                    session_id=session_id,
                    results=persisted_results,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("chat persist (tool batch) failed: %s", exc)

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
