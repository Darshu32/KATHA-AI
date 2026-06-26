"""OpenAI GPT provider implementation — the **primary** agent runtime.

Translates the provider-agnostic types in :mod:`app.agents.runtime.base`
to OpenAI's Chat Completions + function-calling format and back.

OpenAI SDK reference
--------------------
- https://platform.openai.com/docs/api-reference/chat
- https://platform.openai.com/docs/guides/function-calling

We use the streaming Chat Completions API (``client.chat.completions
.create(stream=True)``) so the agent loop can surface text deltas and
tool calls in real time. Tool-call arguments arrive as JSON fragments
spread across many deltas, keyed by ``index``; we accumulate them and
parse once the stream finishes.

Why OpenAI is primary
---------------------
Per the platform decision (Option B), OpenAI is the main agent brain
for chat + reasoning. The Anthropic SDK is retained, but only for the
vision provider (:mod:`app.vision.anthropic_vision`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.agents.runtime.base import (
    AgentMessage,
    AgentProvider,
    AssistantContent,
    ProviderConfig,
    ProviderEvent,
    TextContent,
    ToolCallContent,
    ToolResultContent,
    UsageStats,
)

log = logging.getLogger(__name__)


class OpenAIProvider(AgentProvider):
    name = "openai"

    def __init__(self) -> None:
        # Lazy-import so importing this module without the SDK
        # installed (e.g. running unit tests) doesn't crash.
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "openai SDK not installed. Run "
                "`pip install -r backend/requirements.txt`."
            ) from exc
        self._sdk = AsyncOpenAI
        self._client_cache: dict[tuple[str, str | None], Any] = {}

    def _client(self, api_key: str, base_url: str | None) -> Any:
        key = (api_key, base_url)
        if key not in self._client_cache:
            self._client_cache[key] = self._sdk(
                api_key=api_key,
                base_url=base_url,
            )
        return self._client_cache[key]

    # ── Translation: KATHA messages → OpenAI messages ───────────────

    @staticmethod
    def _to_openai_messages(
        messages: list[AgentMessage],
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        """OpenAI uses a flat list of messages. Unlike Anthropic there
        is no separate ``system`` parameter — the system prompt is the
        first message with ``role: system``.

        Tool calls live on the assistant message as a ``tool_calls``
        array; tool results are separate messages with ``role: tool``
        carrying a ``tool_call_id``.
        """
        out: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        for msg in messages:
            if msg.role == "system":
                # Fold any extra system turns into a system message.
                if isinstance(msg.content, str) and msg.content:
                    out.append({"role": "system", "content": msg.content})
                continue

            if msg.role == "user":
                if isinstance(msg.content, str):
                    out.append({"role": "user", "content": msg.content})
                    continue
                # List of ToolResultContent → one `tool` message each.
                # (TextContent in a user list is rare; fold into a user msg.)
                pending_text: list[str] = []
                for item in msg.content:  # type: ignore[union-attr]
                    if isinstance(item, ToolResultContent):
                        out.append(
                            {
                                "role": "tool",
                                "tool_call_id": item.tool_call_id,
                                "content": _coerce_to_text(item.output),
                            }
                        )
                    elif isinstance(item, TextContent):
                        pending_text.append(item.text)
                if pending_text:
                    out.append(
                        {"role": "user", "content": "\n".join(pending_text)}
                    )

            elif msg.role == "assistant":
                items = (
                    msg.content
                    if isinstance(msg.content, list)
                    else [TextContent(text=str(msg.content))]
                )
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for item in items:
                    if isinstance(item, TextContent):
                        if item.text:
                            text_parts.append(item.text)
                    elif isinstance(item, ToolCallContent):
                        tool_calls.append(
                            {
                                "id": item.id,
                                "type": "function",
                                "function": {
                                    "name": item.name,
                                    "arguments": json.dumps(
                                        item.input, default=str
                                    ),
                                },
                            }
                        )
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                # OpenAI requires content to be present; null is allowed
                # only when tool_calls is set.
                assistant_msg["content"] = (
                    "\n".join(text_parts) if text_parts else None
                )
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                out.append(assistant_msg)

        return out

    @staticmethod
    def _to_openai_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """KATHA tool shape ``{name, description, input_schema}`` →
        OpenAI ``{type: function, function: {name, description,
        parameters}}``.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    # ── Stream ──────────────────────────────────────────────────────

    async def stream(
        self,
        messages: list[AgentMessage],
        config: ProviderConfig,
    ) -> AsyncIterator[ProviderEvent]:
        client = self._client(config.api_key, config.base_url)
        openai_messages = self._to_openai_messages(
            messages, config.system_prompt
        )
        openai_tools = self._to_openai_tools(config.tools)

        # Accumulators for the final ``message_done`` event.
        text_buffer: list[str] = []
        # Tool-call fragments arrive across deltas keyed by `index`.
        # Each entry: {"id": str, "name": str, "args": [chunks]}.
        tool_fragments: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage = UsageStats()

        try:
            kwargs: dict[str, Any] = dict(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                messages=openai_messages,
                stream=True,
                # Ask for usage on the final chunk (supported by
                # Chat Completions streaming).
                stream_options={"include_usage": True},
            )
            if openai_tools:
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"

            stream = await client.chat.completions.create(**kwargs)

            async for chunk in stream:
                # Usage-only chunks (the last one) have empty choices.
                if getattr(chunk, "usage", None):
                    usage = UsageStats(
                        input_tokens=getattr(chunk.usage, "prompt_tokens", 0)
                        or 0,
                        output_tokens=getattr(
                            chunk.usage, "completion_tokens", 0
                        )
                        or 0,
                    )

                if not getattr(chunk, "choices", None):
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # Plain text deltas.
                text_piece = getattr(delta, "content", None)
                if text_piece:
                    text_buffer.append(text_piece)
                    yield ProviderEvent(type="text_delta", text=text_piece)

                # Tool-call deltas (may stream in fragments).
                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = tc.index
                    frag = tool_fragments.setdefault(
                        idx, {"id": "", "name": "", "args": []}
                    )
                    if getattr(tc, "id", None):
                        frag["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            frag["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            frag["args"].append(fn.arguments)

                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason

            # ── Stream finished — assemble the assistant turn. ───────
            assembled: list[AssistantContent] = []
            text = "".join(text_buffer)
            if text:
                assembled.append(TextContent(text=text))

            for idx in sorted(tool_fragments):
                frag = tool_fragments[idx]
                joined = "".join(frag["args"])
                try:
                    parsed = json.loads(joined) if joined else {}
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "tool_call argument parse failed: %s; raw=%r",
                        exc,
                        joined,
                    )
                    parsed = {}
                tool_call = ToolCallContent(
                    id=frag["id"],
                    name=frag["name"],
                    input=parsed,
                )
                assembled.append(tool_call)
                yield ProviderEvent(type="tool_call", tool_call=tool_call)

            yield ProviderEvent(
                type="message_done",
                message=AgentMessage(role="assistant", content=assembled),
                stop_reason=_normalize_finish_reason(finish_reason),
                usage=usage,
            )
            return

        except Exception as exc:  # noqa: BLE001
            log.exception("openai stream failed")
            yield ProviderEvent(
                type="error", error=f"{type(exc).__name__}: {exc}"
            )
            return


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _coerce_to_text(value: Any) -> str:
    """OpenAI's tool message wants a string. Serialize anything else."""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _normalize_finish_reason(value: Any) -> str:
    """Map OpenAI finish_reason to the small set in :class:`StopReason`."""
    if value == "tool_calls":
        return "tool_use"
    if value == "length":
        return "max_tokens"
    # "stop", None, or anything else → a normal completed turn.
    return "end_turn"
