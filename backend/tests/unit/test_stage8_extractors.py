"""Stage 8 unit tests — extractor semantics + tool registry shape.

These tests don't touch a DB. They exercise the deterministic
:func:`extract_architect_fingerprint` + :func:`extract_client_pattern`
in isolation, plus the tool registry contract for Stage 8's 5 new
tools.
"""

from __future__ import annotations

import pytest

from app.profiles import (
    ArchitectFingerprint,
    ClientPattern,
    extract_architect_fingerprint,
    extract_client_pattern,
)


# ─────────────────────────────────────────────────────────────────────
# extract_architect_fingerprint
# ─────────────────────────────────────────────────────────────────────


def _graph(theme: str, room_type: str, lwh: tuple[float, float, float],
           materials: list[str], palette: list[str] | None = None) -> dict:
    return {
        "room": {
            "type": room_type,
            "dimensions": {
                "length": lwh[0], "width": lwh[1], "height": lwh[2],
            },
        },
        "objects": [],
        "materials": [{"name": m, "category": "wood"} for m in materials],
        "style": {
            "primary": theme,
            "palette": [{"hex": h} for h in (palette or [])],
        },
    }


def test_architect_fingerprint_empty_inputs():
    fp = extract_architect_fingerprint(user_id="u-1", design_graphs=[])
    assert isinstance(fp, ArchitectFingerprint)
    assert fp.user_id == "u-1"
    assert fp.project_count == 0
    assert fp.preferred_themes == []


def test_architect_fingerprint_counts_themes_with_share():
    graphs = [
        _graph("modern", "living_room", (5.0, 4.0, 2.7), ["walnut"]),
        _graph("modern", "bedroom", (4.0, 3.5, 2.7), ["walnut", "brass"]),
        _graph("scandinavian", "kitchen", (5.5, 4.0, 2.7), ["oak"]),
    ]
    fp = extract_architect_fingerprint(user_id="u-1", design_graphs=graphs)
    assert fp.project_count == 3
    themes_by_name = {t["name"]: t for t in fp.preferred_themes}
    assert "modern" in themes_by_name
    assert themes_by_name["modern"]["count"] == 2
    assert themes_by_name["modern"]["share"] == pytest.approx(2 / 3, rel=1e-3)
    assert themes_by_name["scandinavian"]["count"] == 1


def test_architect_fingerprint_typical_dims_are_medians():
    graphs = [
        _graph("modern", "x", (4.0, 3.0, 2.7), []),
        _graph("modern", "x", (5.0, 4.0, 2.7), []),
        _graph("modern", "x", (6.0, 5.0, 2.7), []),
    ]
    fp = extract_architect_fingerprint(user_id="u-1", design_graphs=graphs)
    assert fp.typical_room_dimensions_m["length"] == 5.0  # median of 4/5/6
    assert fp.typical_room_dimensions_m["width"] == 4.0
    assert fp.typical_room_dimensions_m["height"] == 2.7


def test_architect_fingerprint_palette_dedups_by_count():
    graphs = [
        _graph("m", "x", (4, 3, 2.7), [], palette=["#5c3d2e", "#f4ede0"]),
        _graph("m", "x", (4, 3, 2.7), [], palette=["#5c3d2e"]),
    ]
    fp = extract_architect_fingerprint(user_id="u", design_graphs=graphs)
    # #5c3d2e appears twice → comes first.
    assert fp.preferred_palette_hexes[0] == "#5c3d2e"
    assert "#f4ede0" in fp.preferred_palette_hexes


def test_architect_fingerprint_tool_usage_from_audit_events():
    events = [
        {"action": "tool_call", "after": {"tool": "estimate_project_cost"}},
        {"action": "tool_call", "after": {"tool": "estimate_project_cost"}},
        {"action": "tool_call", "after": {"tool": "search_knowledge"}},
        {"action": "create", "after": {"tool": "ignored"}},  # not a tool_call
    ]
    fp = extract_architect_fingerprint(
        user_id="u", design_graphs=[], tool_calls=events,
    )
    by_name = {t["name"]: t for t in fp.tool_usage}
    assert by_name["estimate_project_cost"]["count"] == 2
    assert by_name["search_knowledge"]["count"] == 1
    # 'ignored' was not a tool_call action — must be excluded.
    assert "ignored" not in by_name
    # Shares sum to 1.0 over the 3 valid events.
    total_share = sum(t["share"] for t in fp.tool_usage)
    assert total_share == pytest.approx(1.0, rel=1e-3)


def test_architect_fingerprint_handles_partial_graphs_gracefully():
    """Defensive against missing fields — don't crash, just skip."""
    graphs = [
        {},  # no anything
        {"room": {}},
        {"style": "modern"},  # style as bare string instead of dict
        {"objects": [{"material": "TEAK"}]},  # only object material
    ]
    fp = extract_architect_fingerprint(user_id="u", design_graphs=graphs)
    assert fp.project_count == 4
    # The "modern" style as a bare string still gets counted.
    assert any(t["name"] == "modern" for t in fp.preferred_themes)
    # Object material was lowercased.
    assert any(m["name"] == "teak" for m in fp.preferred_materials)


# ─────────────────────────────────────────────────────────────────────
# extract_client_pattern
# ─────────────────────────────────────────────────────────────────────


def test_client_pattern_empty_inputs():
    out = extract_client_pattern(client_id="c-1", projects=[])
    assert isinstance(out, ClientPattern)
    assert out.client_id == "c-1"
    assert out.project_count == 0


def test_client_pattern_budget_summary_low_high_median():
    projects = [
        {"estimate_total_inr": 100_000},
        {"estimate_total_inr": 200_000},
        {"estimate_total_inr": 500_000},
    ]
    out = extract_client_pattern(client_id="c-1", projects=projects)
    assert out.typical_budget_inr["low"] == 100_000
    assert out.typical_budget_inr["high"] == 500_000
    assert out.typical_budget_inr["median"] == 200_000
    assert out.typical_budget_inr["samples"] == 3


def test_client_pattern_recurring_room_types():
    projects = [
        {"room_type": "kitchen"},
        {"room_type": "kitchen"},
        {"graph_data": {"room": {"type": "bedroom"}}},
    ]
    out = extract_client_pattern(client_id="c", projects=projects)
    by_name = {r["name"]: r for r in out.recurring_room_types}
    assert by_name["kitchen"]["count"] == 2
    assert by_name["bedroom"]["count"] == 1


def test_client_pattern_accessibility_from_decisions():
    projects = [
        {
            "decisions": [
                {"tags": ["accessibility", "client_request"]},
                {"tags": ["budget"]},
            ],
        },
        {
            "accessibility_flags": ["wheelchair_ramp"],
        },
    ]
    out = extract_client_pattern(client_id="c", projects=projects)
    assert "derived_from_decision" in out.accessibility_flags
    assert "wheelchair_ramp" in out.accessibility_flags


def test_client_pattern_recurring_constraints_only_keeps_repeats():
    """A constraint phrase that appears once doesn't graduate to
    'recurring' — only ≥ 2 occurrences."""
    projects = [
        {"description": "north-facing balcony; budget conscious"},
        {"description": "budget conscious"},
        {"description": "south-facing"},
    ]
    out = extract_client_pattern(client_id="c", projects=projects)
    assert "budget conscious" in out.constraints
    # "north-facing balcony" appears once — not a pattern.
    assert "north-facing balcony" not in out.constraints
    # "south-facing" appears once.
    assert "south-facing" not in out.constraints


def test_client_pattern_handles_missing_fields():
    projects = [{}, {"description": ""}, {"estimate_total_inr": "not a number"}]
    out = extract_client_pattern(client_id="c", projects=projects)
    assert out.project_count == 3
    assert out.typical_budget_inr == {}  # no usable budgets


# ─────────────────────────────────────────────────────────────────────
# Tool registry — Stage 8 adds 5
# ─────────────────────────────────────────────────────────────────────


_STAGE_8_TOOLS = {
    "record_design_decision",
    "recall_design_decisions",
    "get_architect_fingerprint",
    "get_client_profile",
    "resume_project_context",
}


def test_all_stage8_tools_registered():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    names = set(REGISTRY.names())
    assert _STAGE_8_TOOLS.issubset(names)


def test_record_design_decision_has_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("record_design_decision")
    assert spec.audit_target_type == "design_decision"


def test_other_decision_tools_are_read_only():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in (
        "recall_design_decisions",
        "get_architect_fingerprint",
        "get_client_profile",
        "resume_project_context",
    ):
        spec = REGISTRY.get(name)
        assert spec.audit_target_type is None, (
            f"{name}: read tool should have no audit_target_type, "
            f"got {spec.audit_target_type!r}"
        )


def test_record_decision_requires_title_and_summary():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("record_design_decision").input_schema()
    required = set(schema.get("required", []))
    assert {"title", "summary"}.issubset(required)


def test_get_architect_fingerprint_takes_no_required_input():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("get_architect_fingerprint").input_schema()
    required = set(schema.get("required", []))
    assert required == set()


def test_resume_project_context_caps_limits():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("resume_project_context").input_schema()
    props = schema["properties"]
    assert props["decision_limit"]["maximum"] == 50
    assert props["version_limit"]["maximum"] == 50


def test_total_tool_count_at_least_72_after_stage8():
    """Stage 7 (67) + Stage 8 (5) = 72."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 72
