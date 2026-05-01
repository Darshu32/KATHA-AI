"""Stage 5 unit tests — DB ↔ runtime translation for chat persistence.

These tests live in ``unit/`` because they don't touch a real DB.
We exercise the row-to-message translator (``_row_to_agent_message``)
and the agent-loop's parallel-dispatch split logic without spinning
up Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.persistence import _row_to_agent_message
from app.agents.runtime import (
    AgentMessage,
    TextContent,
    ToolCallContent,
    ToolResultContent,
)


# ─────────────────────────────────────────────────────────────────────
# _row_to_agent_message
# ─────────────────────────────────────────────────────────────────────


def _row(role: str, content: dict, *, text_preview: str = "") -> SimpleNamespace:
    """Build a fake ChatMessage row with the attrs the translator reads."""
    return SimpleNamespace(
        id="row-id",
        role=role,
        content=content,
        text_preview=text_preview,
    )


def test_user_row_translates_to_user_text_message():
    row = _row("user", {"type": "text", "text": "Design me a kitchen"})
    msg = _row_to_agent_message(row)
    assert isinstance(msg, AgentMessage)
    assert msg.role == "user"
    assert msg.content == "Design me a kitchen"


def test_assistant_row_with_text_block_round_trips():
    row = _row(
        "assistant",
        {"type": "assistant", "blocks": [{"kind": "text", "text": "Sure thing"}]},
    )
    msg = _row_to_agent_message(row)
    assert msg is not None
    assert msg.role == "assistant"
    assert isinstance(msg.content, list)
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], TextContent)
    assert msg.content[0].text == "Sure thing"


def test_assistant_row_with_tool_call_block_round_trips():
    row = _row(
        "assistant",
        {
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
    msg = _row_to_agent_message(row)
    assert msg is not None and isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert isinstance(msg.content[0], TextContent)
    assert isinstance(msg.content[1], ToolCallContent)
    assert msg.content[1].name == "estimate_project_cost"
    assert msg.content[1].input == {"piece_name": "kitchen island"}


def test_assistant_row_with_no_blocks_falls_back_to_preview():
    """An empty assistant row should yield a single text block from
    ``text_preview`` rather than a 0-block message (which the
    provider would reject)."""
    row = _row(
        "assistant",
        {"type": "assistant", "blocks": []},
        text_preview="recovered preview",
    )
    msg = _row_to_agent_message(row)
    assert msg is not None
    assert isinstance(msg.content, list) and len(msg.content) == 1
    assert isinstance(msg.content[0], TextContent)
    assert msg.content[0].text == "recovered preview"


def test_tool_results_row_becomes_user_message_with_result_blocks():
    row = _row(
        "tool",
        {
            "type": "tool_results",
            "results": [
                {"tool_call_id": "tc-1", "ok": True, "output": {"total_inr": 12345}},
                {"tool_call_id": "tc-2", "ok": False, "error": {"type": "timeout"}},
            ],
        },
    )
    msg = _row_to_agent_message(row)
    assert msg is not None
    # Tool results are wrapped in a user-role message Anthropic-style.
    assert msg.role == "user"
    assert isinstance(msg.content, list) and len(msg.content) == 2
    assert all(isinstance(c, ToolResultContent) for c in msg.content)
    assert msg.content[0].is_error is False
    assert msg.content[0].output == {"total_inr": 12345}
    assert msg.content[1].is_error is True
    assert msg.content[1].output == {"type": "timeout"}


def test_tool_row_with_no_results_returns_none():
    """An empty tool batch wouldn't help the provider — drop it."""
    row = _row("tool", {"type": "tool_results", "results": []})
    assert _row_to_agent_message(row) is None


def test_unknown_role_returns_none():
    row = _row("system", {"type": "text", "text": "ignored"})
    assert _row_to_agent_message(row) is None


def test_corrupt_content_does_not_raise():
    """A row with garbage content should be skipped, not crash the
    whole resumption."""
    bad = _row("assistant", "not-a-dict-at-all")  # type: ignore[arg-type]
    # The translator returns None instead of bubbling up.
    assert _row_to_agent_message(bad) is None


# ─────────────────────────────────────────────────────────────────────
# Parallel-dispatch sanity (registry-level)
# ─────────────────────────────────────────────────────────────────────


def test_readonly_tools_have_no_audit_target_for_parallel_safety():
    """The agent loop uses ``audit_target_type is None`` as the proxy
    for "safe to run in parallel". Verify a representative sample of
    read-only Stage 4A tools indeed have None."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in (
        "lookup_theme",
        "list_themes",
        "check_door_width",
        "lookup_climate_zone",
        "list_qa_gates",
        "lookup_ergonomic_envelope",
        "list_design_versions",  # Stage 4G read tool
        "list_export_formats",   # Stage 4H discovery
        "recall_recent_chat",    # Stage 5 itself — must be read-only
    ):
        spec = REGISTRY.get(name)
        assert spec.audit_target_type is None, (
            f"{name} expected read-only but has audit_target_type "
            f"{spec.audit_target_type!r} — would force serial dispatch"
        )


def test_write_tools_have_audit_targets_so_they_run_serially():
    """Write tools should declare an audit target — both for the audit
    log AND so the parallel-dispatch split correctly serialises them."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in (
        "estimate_project_cost",
        "generate_initial_design",
        "apply_theme",
        "edit_design_object",
        "export_design_bundle",
    ):
        spec = REGISTRY.get(name)
        assert spec.audit_target_type, (
            f"{name} is a write tool but has no audit_target_type; "
            "the parallel dispatcher would treat it as read-only"
        )


def test_recall_tool_registered_with_correct_shape():
    """Stage 5 recall tool: read-only, sensible timeout, no required input."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("recall_recent_chat")
    assert spec.audit_target_type is None
    assert spec.timeout_seconds <= 60.0
    schema = spec.input_schema()
    required = set(schema.get("required", []))
    assert required == set(), (
        f"recall_recent_chat should have no required fields, got {required}"
    )
    # limit field has the bounded range.
    props = schema.get("properties", {})
    assert "limit" in props
    assert props["limit"].get("minimum") == 1
    assert props["limit"].get("maximum") == 50
