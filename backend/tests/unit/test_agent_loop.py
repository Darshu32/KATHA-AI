"""Tests for the architect agent loop using a fake provider.

The loop's control flow is independent of the provider — these tests
script the provider's event stream and verify the loop:

  - Emits ``thinking`` for text before any tool call.
  - Emits ``tool_call`` + ``tool_result`` for each tool the model uses.
  - Re-enters the provider after tool results until ``stop_reason ==
    end_turn``.
  - Emits a single ``done`` event with cumulative usage + iteration count.
  - Bails out cleanly on errors.

No DB. No network. No LLM. Pure orchestration test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents.architect_agent import run_architect_agent
from app.agents.runtime.base import (
    AgentMessage,
    AgentProvider,
    ProviderConfig,
    ProviderEvent,
    TextContent,
    ToolCallContent,
    UsageStats,
)
from app.agents.stream import (
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.agents.tool import REGISTRY, ToolContext, ToolSpec


# ─────────────────────────────────────────────────────────────────────
# Fake provider
# ─────────────────────────────────────────────────────────────────────


class _ScriptedProvider(AgentProvider):
    """Plays back a list of pre-recorded :class:`ProviderEvent` lists.

    Each ``stream()`` call pops the next list. Use this to script
    exactly how the LLM "behaves" in a turn.
    """

    name = "scripted"

    def __init__(self, scripts: list[list[ProviderEvent]]) -> None:
        self._scripts = list(scripts)
        self.calls = 0

    async def stream(
        self, messages: list[AgentMessage], config: ProviderConfig
    ) -> AsyncIterator[ProviderEvent]:
        self.calls += 1
        if not self._scripts:
            raise RuntimeError("scripted provider exhausted")
        for ev in self._scripts.pop(0):
            yield ev


# ─────────────────────────────────────────────────────────────────────
# Test tool — registered fresh per test run
# ─────────────────────────────────────────────────────────────────────


class _EchoIn(BaseModel):
    text: str


class _EchoOut(BaseModel):
    echoed: str


async def _echo_fn(ctx: ToolContext, input: _EchoIn) -> _EchoOut:
    return _EchoOut(echoed=input.text.upper())


@pytest.fixture
def echo_tool_registered():
    """Inject an `echo` tool into the GLOBAL registry for one test."""
    name = "echo"
    if name in REGISTRY.names():
        # Avoid duplicates across test runs.
        return
    spec = ToolSpec(
        name=name,
        description="Echo a string back uppercased",
        input_model=_EchoIn,
        output_model=_EchoOut,
        fn=_echo_fn,
    )
    REGISTRY.register(spec)


@pytest.fixture
def fake_ctx():
    """ToolContext that doesn't need a real DB session for our echo test."""
    return ToolContext(session=None, actor_id=None, request_id="test-req")  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _stub_anthropic_key(monkeypatch):
    """Avoid the no-key guard in run_architect_agent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from app.config import get_settings
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────
# Loop control flow
# ─────────────────────────────────────────────────────────────────────


async def test_simple_text_response(fake_ctx, echo_tool_registered):
    """Provider emits text only; no tool call; loop ends after one iter."""
    provider = _ScriptedProvider([[
        ProviderEvent(type="text_delta", text="Hello "),
        ProviderEvent(type="text_delta", text="architect"),
        ProviderEvent(
            type="message_done",
            message=AgentMessage(
                role="assistant",
                content=[TextContent(text="Hello architect")],
            ),
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=2),
        ),
    ]])

    events = []
    async for ev in run_architect_agent(
        user_message="Hi",
        ctx=fake_ctx,
        provider=provider,
    ):
        events.append(ev)

    assert provider.calls == 1
    # No tool call seen → text deltas became `thinking` events.
    text_chunks = [e for e in events if isinstance(e, ThinkingEvent)]
    assert "".join(e.text for e in text_chunks) == "Hello architect"
    # No tool calls expected.
    assert not any(isinstance(e, ToolCallEvent) for e in events)
    # Done with end_turn.
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1 and done[0].stop_reason == "end_turn"
    assert done[0].input_tokens == 10 and done[0].output_tokens == 2


async def test_tool_call_then_text(fake_ctx, echo_tool_registered):
    """Provider calls echo, then on next iteration emits final text."""
    iter_1 = [
        ProviderEvent(type="text_delta", text="Let me check..."),
        ProviderEvent(
            type="tool_call",
            tool_call=ToolCallContent(id="call-1", name="echo", input={"text": "hello"}),
        ),
        ProviderEvent(
            type="message_done",
            message=AgentMessage(
                role="assistant",
                content=[
                    TextContent(text="Let me check..."),
                    ToolCallContent(id="call-1", name="echo", input={"text": "hello"}),
                ],
            ),
            stop_reason="tool_use",
            usage=UsageStats(input_tokens=20, output_tokens=8),
        ),
    ]
    iter_2 = [
        ProviderEvent(type="text_delta", text="Got HELLO."),
        ProviderEvent(
            type="message_done",
            message=AgentMessage(
                role="assistant",
                content=[TextContent(text="Got HELLO.")],
            ),
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=30, output_tokens=4),
        ),
    ]
    provider = _ScriptedProvider([iter_1, iter_2])

    events = []
    async for ev in run_architect_agent(
        user_message="echo hello",
        ctx=fake_ctx,
        provider=provider,
    ):
        events.append(ev)

    assert provider.calls == 2

    # Tool call surfaced, tool result followed.
    tc = [e for e in events if isinstance(e, ToolCallEvent)]
    tr = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tc) == 1 and tc[0].name == "echo"
    assert len(tr) == 1 and tr[0].ok is True
    assert tr[0].output == {"echoed": "HELLO"}

    # Iter 1 text was thinking (before tool); iter 2 text was final text.
    thinking = [e for e in events if isinstance(e, ThinkingEvent)]
    final_text = [e for e in events if isinstance(e, TextEvent)]
    assert "".join(e.text for e in thinking) == "Let me check..."
    assert "".join(e.text for e in final_text) == "Got HELLO."

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1 and done[0].stop_reason == "end_turn"
    assert done[0].iterations == 2
    # Cumulative usage (10+30 in, 2+4 out... actually 20+30=50 input, 8+4=12 output).
    assert done[0].input_tokens == 50
    assert done[0].output_tokens == 12


async def test_provider_error_emits_error_event(fake_ctx, echo_tool_registered):
    provider = _ScriptedProvider([[
        ProviderEvent(type="error", error="boom"),
    ]])
    events = []
    async for ev in run_architect_agent(
        user_message="",
        ctx=fake_ctx,
        provider=provider,
    ):
        events.append(ev)

    err = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(err) == 1 and "boom" in err[0].message
    # No `done` after error.
    assert not any(isinstance(e, DoneEvent) for e in events)


async def test_no_anthropic_key_emits_error(fake_ctx, monkeypatch):
    """Loop refuses to start if ANTHROPIC_API_KEY is empty."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    # Use a provider that pretends to be anthropic — the loop should
    # bail before calling it.
    class _DummyAnthropic(AgentProvider):
        name = "anthropic"
        async def stream(self, messages, config):
            yield ProviderEvent(type="error", error="should never be called")

    events = []
    async for ev in run_architect_agent(
        user_message="x",
        ctx=fake_ctx,
        provider=_DummyAnthropic(),
    ):
        events.append(ev)
    assert any(
        isinstance(e, ErrorEvent) and "ANTHROPIC_API_KEY" in e.message
        for e in events
    )


# ─────────────────────────────────────────────────────────────────────
# SSE encoder
# ─────────────────────────────────────────────────────────────────────


def test_sse_encoding_round_trip():
    from app.agents.stream import StreamFormatter, ToolCallEvent

    ev = ToolCallEvent(id="abc", name="echo", input={"text": "x"})
    raw = StreamFormatter.encode(ev)
    text = raw.decode("utf-8")
    assert text.startswith("event: tool_call\n")
    assert "data: " in text
    assert text.endswith("\n\n")
    # Payload doesn't carry the redundant "event" key.
    assert '"event"' not in text
