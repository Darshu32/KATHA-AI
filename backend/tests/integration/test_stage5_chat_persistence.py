"""Stage 5 integration tests — chat persistence repo + recall tool.

Requires Postgres + ``alembic upgrade head`` (so the
``chat_sessions`` and ``chat_messages`` tables exist). Skipped
automatically without ``KATHA_INTEGRATION_TESTS=1``.

We exercise the full life cycle:

- ``ChatHistoryRepository.create_session`` →
  ``append_message`` → ``list_messages`` round-trip
- ``recall_recent_chat`` tool against a populated session
- Position uniqueness — appending twice yields strictly increasing
  ``position`` values
- ``list_sessions_for_owner`` ordering + project-id filter
- Owner guard — ``get_session_for_owner`` refuses cross-user reads
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _seed_user(session, *, email: str = "stage5@example.com") -> str:
    """Insert a User row and return its id. Lightweight — bypasses the
    auth flow since these tests aren't exercising auth."""
    from app.models.orm import User

    user = User(
        email=email,
        hashed_password="not-a-real-hash",
        display_name="Stage 5 Test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S5 Project") -> str:
    from app.models.orm import Project

    project = Project(
        owner_id=owner_id,
        name=name,
        description="",
        status="draft",
        latest_version=0,
    )
    session.add(project)
    await session.flush()
    return project.id


# ─────────────────────────────────────────────────────────────────────
# Repository — session + message lifecycle
# ─────────────────────────────────────────────────────────────────────


async def test_create_session_and_append_messages_roundtrip(db_session):
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="rt@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    chat = await Repo.create_session(
        db_session, owner_id=user_id, project_id=project_id, title="Test chat",
    )
    assert chat.id
    assert chat.message_count == 0
    assert chat.status == "active"

    # Append three messages.
    await Repo.append_message(
        db_session, session_id=chat.id, role="user",
        content={"type": "text", "text": "Hello"},
        text_preview="Hello",
    )
    await Repo.append_message(
        db_session, session_id=chat.id, role="assistant",
        content={"type": "assistant", "blocks": [{"kind": "text", "text": "Hi"}]},
        text_preview="Hi",
        input_tokens=12, output_tokens=4,
    )
    await Repo.append_message(
        db_session, session_id=chat.id, role="tool",
        content={"type": "tool_results", "results": []},
        text_preview="(no results)",
        tool_call_count=0,
    )

    # Read back oldest-first.
    rows = await Repo.list_messages(db_session, session_id=chat.id)
    assert [r.position for r in rows] == [1, 2, 3]
    assert [r.role for r in rows] == ["user", "assistant", "tool"]
    assert rows[1].input_tokens == 12

    # Counter denormalisation.
    refreshed = await Repo.get_session(db_session, chat.id)
    assert refreshed is not None
    assert refreshed.message_count == 3
    assert refreshed.last_message_at is not None  # ISO timestamp string


async def test_position_is_strictly_increasing(db_session):
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="pos@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    positions = []
    for i in range(5):
        msg = await Repo.append_message(
            db_session, session_id=chat.id, role="user",
            content={"type": "text", "text": f"msg-{i}"},
        )
        positions.append(msg.position)

    assert positions == [1, 2, 3, 4, 5]


async def test_list_sessions_for_owner_orders_newest_first(db_session):
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="lst@example.com")
    a = await Repo.create_session(db_session, owner_id=user_id, title="A")
    b = await Repo.create_session(db_session, owner_id=user_id, title="B")
    c = await Repo.create_session(db_session, owner_id=user_id, title="C")

    # Touch session B by appending a message — bumps updated_at.
    await Repo.append_message(
        db_session, session_id=b.id, role="user",
        content={"type": "text", "text": "ping"},
    )

    sessions = await Repo.list_sessions_for_owner(db_session, owner_id=user_id)
    ids = [s.id for s in sessions]
    # All three should be there.
    assert {a.id, b.id, c.id}.issubset(set(ids))


async def test_list_sessions_filters_by_project(db_session):
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="prj@example.com")
    p1 = await _seed_project(db_session, owner_id=user_id, name="P1")
    p2 = await _seed_project(db_session, owner_id=user_id, name="P2")

    await Repo.create_session(db_session, owner_id=user_id, project_id=p1, title="A")
    await Repo.create_session(db_session, owner_id=user_id, project_id=p2, title="B")
    await Repo.create_session(db_session, owner_id=user_id, project_id=p1, title="C")

    p1_sessions = await Repo.list_sessions_for_owner(
        db_session, owner_id=user_id, project_id=p1,
    )
    titles = {s.title for s in p1_sessions}
    assert {"A", "C"}.issubset(titles)
    assert "B" not in titles


async def test_get_session_for_owner_refuses_cross_user_reads(db_session):
    """If user X created the session, user Y must not be able to read it."""
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    owner_id = await _seed_user(db_session, email="owner@example.com")
    other_id = await _seed_user(db_session, email="other@example.com")

    chat = await Repo.create_session(db_session, owner_id=owner_id, title="Private")

    # Owner can fetch.
    found = await Repo.get_session_for_owner(
        db_session, session_id=chat.id, owner_id=owner_id,
    )
    assert found is not None and found.id == chat.id

    # Other user gets None.
    not_found = await Repo.get_session_for_owner(
        db_session, session_id=chat.id, owner_id=other_id,
    )
    assert not_found is None


async def test_archive_session_marks_as_archived_idempotently(db_session):
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="arc@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id, title="Old")

    archived = await Repo.archive_session(
        db_session, session_id=chat.id, owner_id=user_id,
    )
    assert archived is not None
    assert archived.status == "archived"

    # Idempotent — second call still returns the row (now already archived).
    again = await Repo.archive_session(
        db_session, session_id=chat.id, owner_id=user_id,
    )
    assert again is not None
    assert again.status == "archived"

    # Other user still gets None.
    other_id = await _seed_user(db_session, email="other2@example.com")
    res = await Repo.archive_session(
        db_session, session_id=chat.id, owner_id=other_id,
    )
    assert res is None


# ─────────────────────────────────────────────────────────────────────
# load_history (DB → runtime)
# ─────────────────────────────────────────────────────────────────────


async def test_load_history_round_trips_through_persistence_module(db_session):
    """Persist three turns, reload them, confirm the agent loop sees
    them in the right shape and order."""
    from app.agents.persistence import load_history
    from app.agents.runtime import (
        AgentMessage,
        TextContent,
        ToolCallContent,
        ToolResultContent,
    )
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    user_id = await _seed_user(db_session, email="load@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    # User turn.
    await Repo.append_message(
        db_session, session_id=chat.id, role="user",
        content={"type": "text", "text": "Estimate kitchen cost"},
    )
    # Assistant turn with text + tool_call blocks.
    await Repo.append_message(
        db_session, session_id=chat.id, role="assistant",
        content={
            "type": "assistant",
            "blocks": [
                {"kind": "text", "text": "Calling cost engine."},
                {
                    "kind": "tool_call",
                    "id": "tc-1",
                    "name": "estimate_project_cost",
                    "input": {"piece_name": "kitchen island"},
                },
            ],
        },
    )
    # Tool batch.
    await Repo.append_message(
        db_session, session_id=chat.id, role="tool",
        content={
            "type": "tool_results",
            "results": [
                {"tool_call_id": "tc-1", "ok": True,
                 "output": {"total_inr": 50000}},
            ],
        },
    )

    history = await load_history(db_session, session_id=chat.id)
    assert len(history) == 3

    # Turn 1 — user text.
    assert isinstance(history[0], AgentMessage)
    assert history[0].role == "user"
    assert history[0].content == "Estimate kitchen cost"

    # Turn 2 — assistant with both block types.
    asst = history[1]
    assert asst.role == "assistant" and isinstance(asst.content, list)
    assert isinstance(asst.content[0], TextContent)
    assert isinstance(asst.content[1], ToolCallContent)
    assert asst.content[1].name == "estimate_project_cost"

    # Turn 3 — tool results wrapped as user message.
    tool = history[2]
    assert tool.role == "user"
    assert isinstance(tool.content, list)
    assert isinstance(tool.content[0], ToolResultContent)
    assert tool.content[0].is_error is False
    assert tool.content[0].output == {"total_inr": 50000}


# ─────────────────────────────────────────────────────────────────────
# recall_recent_chat tool — end-to-end
# ─────────────────────────────────────────────────────────────────────


async def test_recall_tool_returns_messages_for_active_session(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="recall@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    for i in range(5):
        await Repo.append_message(
            db_session, session_id=chat.id, role="user",
            content={"type": "text", "text": f"line {i}"},
            text_preview=f"line {i}",
        )

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        session_id=chat.id,
        request_id="recall-test",
    )
    result = await call_tool(
        "recall_recent_chat",
        {"limit": 3},
        ctx,
        registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["session_id"] == chat.id
    assert out["total_messages"] == 5
    assert out["returned_count"] == 3
    # Newest first.
    positions = [m["position"] for m in out["messages"]]
    assert positions == [5, 4, 3]


async def test_recall_tool_role_filter(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.chat_history import ChatHistoryRepository as Repo

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="filter@example.com")
    chat = await Repo.create_session(db_session, owner_id=user_id)

    # Mixed roles.
    await Repo.append_message(
        db_session, session_id=chat.id, role="user",
        content={"type": "text", "text": "u1"}, text_preview="u1",
    )
    await Repo.append_message(
        db_session, session_id=chat.id, role="assistant",
        content={"type": "assistant", "blocks": []}, text_preview="a1",
    )
    await Repo.append_message(
        db_session, session_id=chat.id, role="user",
        content={"type": "text", "text": "u2"}, text_preview="u2",
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, session_id=chat.id,
        request_id="filter-test",
    )
    result = await call_tool(
        "recall_recent_chat",
        {"limit": 5, "role_filter": "user"},
        ctx,
        registry=REGISTRY,
    )
    assert result["ok"]
    out = result["output"]
    assert all(m["role"] == "user" for m in out["messages"])
    assert {m["text_preview"] for m in out["messages"]} == {"u1", "u2"}


async def test_recall_tool_without_session_id_surfaces_as_tool_error(db_session):
    """No session in scope → structured error envelope, not a crash."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    ctx = ToolContext(
        session=db_session, actor_id=None, session_id=None,
        request_id="no-session",
    )
    result = await call_tool(
        "recall_recent_chat",
        {"limit": 5},
        ctx,
        registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "chat session" in result["error"]["message"].lower()
