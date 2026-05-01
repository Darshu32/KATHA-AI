"""Stage 10 unit tests — BRD gap-closure tools registered + schema'd.

Stage 10 wraps three pre-existing services as agent tools so the
BRD §1A brief / §4D sensitivity / §6 recommendations capabilities
become callable from chat. These tests don't touch the DB or the
LLM — they exercise:

- Registry shape — all 5 new tools are present.
- Audit-target correctness — only ``analyze_cost_shock`` writes
  audit (the LLM advisor is the heaviest call). Brief + recs
  tools are read-only.
- Input-schema completeness — the BRD-required fields are present
  on each tool's input model.
- Total tool count — 73 (post Stage 9) + 5 (Stage 10) = 78.
"""

from __future__ import annotations


_STAGE_10_TOOLS = {
    "intake_design_brief",
    "brief_to_generation_context",
    "analyze_cost_shock",
    "quick_recommendations",
    "full_recommendations",
}


# ─────────────────────────────────────────────────────────────────────
# Registry presence + audit targets
# ─────────────────────────────────────────────────────────────────────


def test_all_stage10_tools_registered():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    names = set(REGISTRY.names())
    assert _STAGE_10_TOOLS.issubset(names), (
        f"missing: {_STAGE_10_TOOLS - names}"
    )


def test_analyze_cost_shock_has_audit_target():
    """LLM-driven cost analysis writes audit so we can trace which
    projects ran sensitivity."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("analyze_cost_shock")
    assert spec.audit_target_type == "cost_sensitivity_analysis"


def test_other_stage10_tools_are_read_only():
    """Brief intake + recommendations don't mutate state — no audit."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in (
        "intake_design_brief",
        "brief_to_generation_context",
        "quick_recommendations",
        "full_recommendations",
    ):
        spec = REGISTRY.get(name)
        assert spec.audit_target_type is None, (
            f"{name}: read tool should have no audit_target_type, "
            f"got {spec.audit_target_type!r}"
        )


# ─────────────────────────────────────────────────────────────────────
# Brief schema — all 5 BRD §1A sections required
# ─────────────────────────────────────────────────────────────────────


def test_intake_design_brief_requires_brd_5_sections():
    """BRD §1A specifies 5 sections — project_type, theme, space,
    requirements, regulatory. Lock the first 4 as required (regulatory
    is defaulted from city)."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("intake_design_brief").input_schema()
    required = set(schema.get("required", []))
    assert {"project_type", "theme", "space", "requirements"}.issubset(
        required
    ), f"expected BRD §1A core sections; got required={required}"


def test_brief_to_context_takes_same_shape():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("brief_to_generation_context").input_schema()
    required = set(schema.get("required", []))
    assert {"project_type", "theme", "space", "requirements"}.issubset(
        required
    )


# ─────────────────────────────────────────────────────────────────────
# Sensitivity — BRD §4D ±10% defaults
# ─────────────────────────────────────────────────────────────────────


def test_analyze_cost_shock_defaults_to_brd_10_percent():
    """BRD §4D specifies ±10% as the canonical shock magnitude."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("analyze_cost_shock").input_schema()
    props = schema.get("properties", {})
    shock = props.get("shock_pct", {})
    assert shock.get("default") == 10.0, (
        f"expected BRD §4D default of 10.0, got {shock.get('default')}"
    )
    assert shock.get("maximum") == 50, "shock cap must be 50%"


def test_analyze_cost_shock_volume_default_matches_brd():
    """BRD §4D: 1 / 5 / 10 piece scenarios as default volumes."""
    from app.agents.tools.sensitivity import AnalyzeCostShockInput

    inst = AnalyzeCostShockInput(
        cost_engine={"x": 1}, pricing_buildup={"y": 1},
    )
    assert inst.volumes == [1, 5, 10]


def test_analyze_cost_shock_requires_cost_engine_and_pricing():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("analyze_cost_shock").input_schema()
    required = set(schema.get("required", []))
    assert {"cost_engine", "pricing_buildup"}.issubset(required)


# ─────────────────────────────────────────────────────────────────────
# Recommendations — BRD §6 categories + proactive vs advisor split
# ─────────────────────────────────────────────────────────────────────


def test_quick_recommendations_takes_design_graph():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("quick_recommendations").input_schema()
    required = set(schema.get("required", []))
    assert "design_graph" in required


def test_full_recommendations_optional_fields_default_safely():
    """The LLM advisor has no required fields — every field has a
    sensible default. Lets the agent call it with whatever context
    it has."""
    from app.agents.tools.recommendations import FullRecommendationsInput

    inst = FullRecommendationsInput()
    assert inst.complexity == "moderate"
    assert inst.units == 1


def test_full_recommendations_caps_units_at_10000():
    """Sanity check — no infinite-volume scenarios."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("full_recommendations").input_schema()
    props = schema.get("properties", {})
    assert props["units"]["maximum"] == 10000


# ─────────────────────────────────────────────────────────────────────
# Total tool count
# ─────────────────────────────────────────────────────────────────────


def test_total_tool_count_at_least_78_after_stage10():
    """Stage 9 (73) + Stage 10 (5) = 78."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 78


# ─────────────────────────────────────────────────────────────────────
# Smoke — quick_recommendations actually runs over a graph
# ─────────────────────────────────────────────────────────────────────


def test_quick_recommend_function_runs_on_minimal_graph():
    """Direct service-level smoke test — deterministic, no LLM."""
    from app.services.recommendations import recommend

    out = recommend({
        "style": {"primary": "mid_century_modern"},
        "materials": [{"name": "oak", "category": "wood"}],
    })
    assert isinstance(out, list)
    # Output may be empty if the graph already aligns with theme
    # defaults; we just want no exceptions.
