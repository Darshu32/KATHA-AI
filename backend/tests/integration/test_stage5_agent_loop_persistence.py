"""Stage 5 integration test — full agent loop with DB-backed persistence.

Drives :func:`run_architect_agent` against:

- A real Postgres session (so chat tables are exercised end-to-end).
- A scripted provider (so no LLM call goes out).
- A real :class:`ToolContext` carrying a chat session_id.

The provider script makes the agent:

1. Produce some thinking text.
2. Call two read-only tools in one iteration (which the loop should
   parallelise).
3. Receive their results and produce a final text turn.

After the loop completes we read the persisted ``chat_messages``
table and confirm the right rows were written in the right order.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.agents.runtime import (
    AgentMessage,
    AgentProvider,
    ProviderConfig,
    ProviderEvent,
    TextContent,
    ToolCallContent,
    UsageStats,
)

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────


class _ScriptedProvider(AgentProvider):
    """Plays back a list of pre-recorded provider event lists."""

    name = "scripted"

    def __init__(self, scripts: list[list[ProviderEvent]]) -> None:
        self._scripts = list(scripts)
        self.calls = 0

    async def stream(
        self, messages: list[AgentMessage], config: ProviderConfig,
    ) -> AsyncIterator[ProviderEvent]:
        self.calls += 1
        if not self._scripts:
            raise RuntimeError("scripted provider exhausted")
        for ev in self._scripts.pop(0):
            yield ev


async def _seed_user(session, email: str) -> str:
    from app.models.orm import User

    user = User(
        email=email,
        hashed_password="x",
        display_name="Stage 5 agent test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


async def test_agent_loop_persists_full_turn_to_db(db_session, monkeypatch):
    """Drive a 2-iteration agent turn and verify every persisted row."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.agents.architect_agent import run_architect_agent
    from app.agents.tool import ToolContext
    from app.agents.tools import ensure_tools_registered
    from app.repositories.chat_history import ChatHistoryRepository as Repo
    ensure_tools_registered()

    user_id = await _seed_user(db_session, email="agent@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    # Iteration 1: assistant calls a read-only tool (list_themes).
    iter_1 = [
        ProviderEvent(type="text_delta", text="Looking up themes…"),
        ProviderEvent(
            type="tool_call",
            tool_call=ToolCallContent(
                id="tc-1", name="list_themes", input={},
            ),
        ),
        ProviderEvent(
            type="message_done",
            message=AgentMessage(
                role="assistant",
                content=[
                    TextContent(text="Looking up themes…"),
                    ToolCallContent(id="tc-1", name="list_themes", input={}),
                ],
            ),
            stop_reason="tool_use",
            usage=UsageStats(input_tokens=20, output_tokens=8),
        ),
    ]
    # Iteration 2: assistant produces a final text reply.
    iter_2 = [
        ProviderEvent(type="text_delta", text="Got it. We have several themes."),
        ProviderEvent(
            type="message_done",
            message=AgentMessage(
                role="assistant",
                content=[TextContent(text="Got it. We have several themes.")],
            ),
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=80, output_tokens=12),
        ),
    ]
    provider = _ScriptedProvider([iter_1, iter_2])

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        session_id=chat.id,
        request_id="t5-agent",
    )

    events = []
    async for ev in run_architect_agent(
        user_message="What themes do I have?",
        ctx=ctx,
        session_id=chat.id,
        provider=provider,
    ):
        events.append(ev)

    # The provider was called twice (one per iteration).
    assert provider.calls == 2

    rows = await Repo.list_messages(db_session, session_id=chat.id)
    # Expected sequence:
    #   1. user        ("What themes do I have?")
    #   2. assistant   (text + tool_call block)  — iteration 1
    #   3. tool        (results from list_themes) — iteration 1 batch
    #   4. assistant   (final text)               — iteration 2
    assert [r.role for r in rows] == ["user", "assistant", "tool", "assistant"]
    assert rows[0].content["text"] == "What themes do I have?"

    # Iter-1 assistant row carries the tool_call block.
    iter_1_blocks = rows[1].content.get("blocks") or []
    kinds = [b.get("kind") for b in iter_1_blocks]
    assert "tool_call" in kinds
    assert rows[1].tool_call_count == 1
    assert rows[1].input_tokens == 20
    assert rows[1].output_tokens == 8

    # Tool batch row.
    results = rows[2].content.get("results") or []
    assert len(results) == 1
    assert results[0]["tool_call_id"] == "tc-1"
    assert results[0]["name"] == "list_themes"
    # The tool may succeed or fail depending on whether themes are
    # seeded; we only assert that the tool was invoked + recorded.
    assert "ok" in results[0]

    # Iter-2 assistant row is plain text.
    iter_2_blocks = rows[3].content.get("blocks") or []
    assert any(b.get("kind") == "text" for b in iter_2_blocks)
    assert rows[3].input_tokens == 80
    assert rows[3].output_tokens == 12


async def test_agent_loop_resumes_history_from_db_when_session_id_set(
    db_session, monkeypatch,
):
    """Pre-seed the chat_messages table, then run a fresh turn —
    the loop should pull history from DB instead of trusting the
    (deliberately mismatched) ``history`` arg."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.agents.architect_agent import run_architect_agent
    from app.agents.tool import ToolContext
    from app.agents.tools import ensure_tools_registered
    from app.repositories.chat_history import ChatHistoryRepository as Repo
    ensure_tools_registered()

    user_id = await _seed_user(db_session, email="resume@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    # Pre-seed: pretend we had two prior turns.
    await Repo.append_message(
        db_session, session_id=chat.id, role="user",
        content={"type": "text", "text": "First message"},
    )
    await Repo.append_message(
        db_session, session_id=chat.id, role="assistant",
        content={
            "type": "assistant",
            "blocks": [{"kind": "text", "text": "First reply"}],
        },
    )

    captured_messages: list[list[AgentMessage]] = []

    class _CaptureProvider(AgentProvider):
        name = "capture"

        async def stream(self, messages, config):
            captured_messages.append(list(messages))
            yield ProviderEvent(
                type="text_delta", text="ack",
            )
            yield ProviderEvent(
                type="message_done",
                message=AgentMessage(
                    role="assistant",
                    content=[TextContent(text="ack")],
                ),
                stop_reason="end_turn",
                usage=UsageStats(input_tokens=5, output_tokens=1),
            )

    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        session_id=chat.id, request_id="resume-test",
    )

    # Pass deliberately misleading client-supplied history. The loop
    # should ignore it because session_id is set.
    bogus_history = [
        AgentMessage(role="user", content="A LIE"),
    ]

    async for _ in run_architect_agent(
        user_message="Third message",
        history=bogus_history,
        ctx=ctx,
        session_id=chat.id,
        provider=_CaptureProvider(),
    ):
        pass

    # The provider got called with: first prior user, first prior
    # assistant, the new user input. Three messages — the bogus
    # history was ignored.
    assert len(captured_messages) == 1
    sent = captured_messages[0]
    assert len(sent) == 3
    assert sent[0].role == "user" and sent[0].content == "First message"
    assert sent[1].role == "assistant"
    assert sent[2].role == "user" and sent[2].content == "Third message"
    # Crucially — "A LIE" never reached the provider.
    assert all(
        getattr(m, "content", "") != "A LIE" for m in sent
    )


async def test_agent_loop_without_session_id_uses_supplied_history(
    db_session, monkeypatch,
):
    """If session_id is None, the loop should use client-supplied
    history verbatim (stateless mode)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.agents.architect_agent import run_architect_agent
    from app.agents.tool import ToolContext
    from app.agents.tools import ensure_tools_registered
    ensure_tools_registered()

    captured: list[list[AgentMessage]] = []

    class _CaptureProvider(AgentProvider):
        name = "capture"

        async def stream(self, messages, config):
            captured.append(list(messages))
            yield ProviderEvent(
                type="message_done",
                message=AgentMessage(
                    role="assistant", content=[TextContent(text="ok")],
                ),
                stop_reason="end_turn",
                usage=UsageStats(input_tokens=1, output_tokens=1),
            )

    user_id = await _seed_user(db_session, email="stateless@example.com")
    ctx = ToolContext(
        session=db_session, actor_id=user_id,
        session_id=None, request_id="stateless-test",
    )

    history = [AgentMessage(role="user", content="prev1")]

    async for _ in run_architect_agent(
        user_message="now",
        history=history,
        ctx=ctx,
        session_id=None,
        provider=_CaptureProvider(),
    ):
        pass

    assert len(captured) == 1
    sent = captured[0]
    assert len(sent) == 2
    assert sent[0].content == "prev1"
    assert sent[1].content == "now"
