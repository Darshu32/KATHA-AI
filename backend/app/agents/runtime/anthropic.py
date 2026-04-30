"""Anthropic Claude provider implementation.

Translates the provider-agnostic types in :mod:`app.agents.runtime.base`
to Anthropic's `Messages` + `tool_use` format and back.

Anthropic SDK reference
-----------------------
- https://docs.anthropic.com/en/api/messages
- https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview

We use the streaming API (``client.messages.stream``) so the agent
loop can surface text deltas and tool calls in real time.
"""

from __future__ import annotations

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


class AnthropicProvider(AgentProvider):
    name = "anthropic"

    def __init__(self) -> None:
        # Lazy-import so importing this module without the SDK
        # installed (e.g. running unit tests) doesn't crash.
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK not installed. Run "
                "`pip install -r backend/requirements.txt`."
            ) from exc
        self._sdk = AsyncAnthropic
        self._client_cache: dict[tuple[str, str | None], Any] = {}

    def _client(self, api_key: str, base_url: str | None) -> Any:
        key = (api_key, base_url)
        if key not in self._client_cache:
            self._client_cache[key] = self._sdk(
                api_key=api_key,
                base_url=base_url,
            )
        return self._client_cache[key]

    # ── Translation: KATHA messages → Anthropic messages ────────────

    @staticmethod
    def _to_anthropic_messages(
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        """Anthropic accepts a top-level ``system`` parameter and a flat
        list of ``user``/``assistant`` messages, each with a
        ``content`` array.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                # System messages handled at top level by caller.
                continue

            if msg.role == "user":
                if isinstance(msg.content, str):
                    out.append({"role": "user", "content": msg.content})
                    continue
                # List of ToolResultContent (or rarely TextContent).
                blocks: list[dict[str, Any]] = []
                for item in msg.content:  # type: ignore[union-attr]
                    if isinstance(item, ToolResultContent):
                        blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": item.tool_call_id,
                                "content": _coerce_to_text(item.output),
                                "is_error": item.is_error,
                            }
                        )
                    elif isinstance(item, TextContent):
                        blocks.append({"type": "text", "text": item.text})
                out.append({"role": "user", "content": blocks})

            elif msg.role == "assistant":
                blocks = []
                items = msg.content if isinstance(msg.content, list) else [
                    TextContent(text=str(msg.content))
                ]
                for item in items:
                    if isinstance(item, TextContent):
                        # Skip empty strings — Anthropic rejects empty text blocks.
                        if item.text:
                            blocks.append({"type": "text", "text": item.text})
                    elif isinstance(item, ToolCallContent):
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": item.id,
                                "name": item.name,
                                "input": item.input,
                            }
                        )
                if not blocks:
                    blocks = [{"type": "text", "text": ""}]  # guard
                out.append({"role": "assistant", "content": blocks})

        return out

    # ── Stream ──────────────────────────────────────────────────────

    async def stream(
        self,
        messages: list[AgentMessage],
        config: ProviderConfig,
    ) -> AsyncIterator[ProviderEvent]:
        client = self._client(config.api_key, config.base_url)
        anthropic_messages = self._to_anthropic_messages(messages)

        # Translate KATHA tool-definition shape to Anthropic's.
        # Both sides use {name, description, input_schema}, so this is
        # a thin pass-through with field-name normalisation.
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in config.tools
        ]

        # Accumulators for the final ``message_done`` event.
        assembled: list[AssistantContent] = []
        # Tool-use blocks build up across `input_json_delta` events; we
        # collect their JSON fragments here keyed by block index.
        partial_tool_inputs: dict[int, dict[str, Any]] = {}
        text_buffers: dict[int, list[str]] = {}
        block_meta: dict[int, dict[str, Any]] = {}
        usage = UsageStats()

        try:
            async with client.messages.stream(
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                system=config.system_prompt,
                tools=anthropic_tools,
                messages=anthropic_messages,
            ) as stream:
                async for event in stream:
                    et = getattr(event, "type", None)

                    if et == "content_block_start":
                        idx = event.index
                        block = event.content_block
                        block_meta[idx] = {
                            "type": block.type,
                            "id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                        }
                        if block.type == "tool_use":
                            partial_tool_inputs[idx] = {}

                    elif et == "content_block_delta":
                        delta = event.delta
                        idx = event.index
                        dt = getattr(delta, "type", None)
                        if dt == "text_delta":
                            chunk = delta.text or ""
                            text_buffers.setdefault(idx, []).append(chunk)
                            yield ProviderEvent(type="text_delta", text=chunk)
                        elif dt == "input_json_delta":
                            # JSON fragments arrive as strings; we collect
                            # them and parse on `content_block_stop`.
                            partial_tool_inputs.setdefault(idx, {}).setdefault(
                                "_chunks", []
                            ).append(delta.partial_json or "")

                    elif et == "content_block_stop":
                        idx = event.index
                        meta = block_meta.get(idx, {})
                        if meta.get("type") == "text":
                            text = "".join(text_buffers.get(idx, []))
                            if text:
                                assembled.append(TextContent(text=text))
                        elif meta.get("type") == "tool_use":
                            chunks = partial_tool_inputs.get(idx, {}).get(
                                "_chunks", []
                            )
                            try:
                                import json
                                joined = "".join(chunks)
                                parsed = json.loads(joined) if joined else {}
                            except Exception as exc:  # noqa: BLE001
                                log.warning(
                                    "tool_use input parse failed: %s; raw=%r",
                                    exc,
                                    joined,
                                )
                                parsed = {}
                            tool_call = ToolCallContent(
                                id=meta.get("id") or "",
                                name=meta.get("name") or "",
                                input=parsed,
                            )
                            assembled.append(tool_call)
                            yield ProviderEvent(type="tool_call", tool_call=tool_call)

                    elif et == "message_delta":
                        # Carries usage + stop_reason on the final delta.
                        delta_usage = getattr(event, "usage", None)
                        if delta_usage is not None:
                            # output_tokens accumulate via deltas.
                            usage.output_tokens = (
                                getattr(delta_usage, "output_tokens", None)
                                or usage.output_tokens
                            )

                    elif et == "message_stop":
                        # Final usage object can come from get_final_message.
                        try:
                            final = await stream.get_final_message()
                            if final.usage:
                                usage = UsageStats(
                                    input_tokens=final.usage.input_tokens or 0,
                                    output_tokens=final.usage.output_tokens or 0,
                                )
                            stop_reason = _normalize_stop_reason(final.stop_reason)
                        except Exception:  # noqa: BLE001
                            stop_reason = "end_turn"

                        yield ProviderEvent(
                            type="message_done",
                            message=AgentMessage(
                                role="assistant",
                                content=assembled,
                            ),
                            stop_reason=stop_reason,
                            usage=usage,
                        )
                        return

        except Exception as exc:  # noqa: BLE001
            log.exception("anthropic stream failed")
            yield ProviderEvent(type="error", error=f"{type(exc).__name__}: {exc}")
            return


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _coerce_to_text(value: Any) -> str:
    """Anthropic's tool_result wants a string. Serialize anything else."""
    if isinstance(value, str):
        return value
    import json
    return json.dumps(value, default=str)


def _normalize_stop_reason(value: Any) -> str:
    """Map Anthropic stop_reason to the small set in :class:`StopReason`."""
    if value in {"tool_use", "end_turn", "max_tokens"}:
        return value
    if value == "stop_sequence":
        return "end_turn"
    return "end_turn"
