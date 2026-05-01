"""Stage 11 unit tests — confidence + provenance retrofit + transparency tools.

Stage 11 retrofits every tool with confidence + provenance via the
framework, and adds 3 new tools (explain_decision,
challenge_design_decision, compare_alternatives). These tests don't
hit a DB or the LLM — they exercise:

- Provenance banner shape — required keys, catalog versions present.
- Confidence kind enumeration — all 78+ existing tools have a kind
  in the curated map (or declare via decorator), and every kind in
  the map maps to a real :data:`KINDS` value.
- Confidence resolution semantics — runtime override beats
  declared kind beats curated map beats unknown.
- Tool registry — 3 new tools registered with correct audit targets.
- Total tool count — 78 + 3 = 81.
"""

from __future__ import annotations

import pytest

from app.agents.confidence import (
    KINDS,
    ConfidenceReport,
    build_confidence,
    kind_for_tool,
)
from app.provenance import (
    HAPTIC_CATALOG_VERSION,
    PROVENANCE_SCHEMA_VERSION,
    TOOLING_GENERATION,
    build_banner,
)


_STAGE_11_TOOLS = {
    "explain_decision",
    "challenge_design_decision",
    "compare_alternatives",
}


# ─────────────────────────────────────────────────────────────────────
# Provenance banner
# ─────────────────────────────────────────────────────────────────────


def test_provenance_banner_has_required_keys():
    b = build_banner()
    for key in (
        "schema_version", "generated_at", "tooling_generation",
        "catalog_versions", "tool", "tool_invocation_kind",
        "request_id",
    ):
        assert key in b, f"missing key {key!r}"


def test_provenance_banner_stamps_versions():
    b = build_banner()
    assert b["schema_version"] == PROVENANCE_SCHEMA_VERSION
    assert b["tooling_generation"] == TOOLING_GENERATION
    cv = b["catalog_versions"]
    assert cv["haptic_catalog"] == HAPTIC_CATALOG_VERSION
    for k in ("haptic_catalog", "haptic_schema", "themes",
              "pricing", "knowledge_corpus"):
        assert k in cv, f"missing catalog version {k!r}"


def test_provenance_banner_carries_tool_stamp():
    b = build_banner(
        tool="export_haptic_payload",
        tool_invocation_kind="agent_call",
        request_id="req-abc",
    )
    assert b["tool"] == "export_haptic_payload"
    assert b["tool_invocation_kind"] == "agent_call"
    assert b["request_id"] == "req-abc"


def test_provenance_banner_extra_overrides_defaults():
    """Extra dict merges on top — caller can override any field."""
    b = build_banner(extra={"tool": "manual_override"})
    assert b["tool"] == "manual_override"


# ─────────────────────────────────────────────────────────────────────
# Confidence kinds + map coverage
# ─────────────────────────────────────────────────────────────────────


def test_kinds_enum_is_stable():
    """Lock the enum — adding a new kind without updating tests
    forces an explicit decision."""
    assert set(KINDS) == {
        "deterministic",
        "static_catalog",
        "rag",
        "llm_validated",
        "llm_self_report",
        "llm_unvalidated",
        "heuristic",
        "io_export",
        "unknown",
    }


def test_every_curated_tool_maps_to_a_real_kind():
    """The curated map's values must all be in KINDS — typo guard."""
    from app.agents.confidence import _DEFAULT_KIND_BY_TOOL

    bad = {n: k for n, k in _DEFAULT_KIND_BY_TOOL.items() if k not in KINDS}
    assert not bad, f"bad confidence kinds in map: {bad}"


def test_kind_for_tool_falls_back_to_unknown():
    assert kind_for_tool("nonexistent_tool_xyz") == "unknown"


def test_kind_for_tool_resolves_known():
    assert kind_for_tool("estimate_project_cost") == "llm_validated"
    assert kind_for_tool("themes_lookup") == "static_catalog"
    assert kind_for_tool("search_knowledge_corpus") == "rag"
    assert kind_for_tool("export_haptic_payload") == "deterministic"


# ─────────────────────────────────────────────────────────────────────
# Confidence resolution semantics
# ─────────────────────────────────────────────────────────────────────


def test_runtime_override_beats_declared_kind():
    rep = build_confidence(
        declared_kind="static_catalog",
        tool_name="some_tool",
        runtime_override={"score": 0.42, "kind": "rag",
                          "factors": ["top_k_similarity"]},
    )
    assert rep.kind == "rag"
    assert rep.score == 0.42
    assert "top_k_similarity" in rep.factors


def test_declared_kind_beats_curated_map():
    """If a tool declares confidence_kind on its decorator, that
    wins over the curated _DEFAULT_KIND_BY_TOOL map."""
    rep = build_confidence(
        declared_kind="deterministic",
        tool_name="estimate_project_cost",  # map says llm_validated
        runtime_override=None,
    )
    assert rep.kind == "deterministic"
    assert rep.score == 1.0


def test_curated_map_beats_unknown():
    rep = build_confidence(
        declared_kind=None,
        tool_name="estimate_project_cost",
        runtime_override=None,
    )
    assert rep.kind == "llm_validated"
    assert rep.score == 0.90


def test_unknown_when_neither_declared_nor_in_map():
    rep = build_confidence(
        declared_kind=None,
        tool_name="totally_unregistered_tool",
        runtime_override=None,
    )
    assert rep.kind == "unknown"
    assert rep.score is None


def test_runtime_override_clamps_score_to_unit_interval():
    rep = build_confidence(
        declared_kind=None, tool_name="x",
        runtime_override={"score": 1.5, "kind": "rag"},
    )
    assert rep.score == 1.0  # clamped
    rep = build_confidence(
        declared_kind=None, tool_name="x",
        runtime_override={"score": -0.2, "kind": "rag"},
    )
    assert rep.score == 0.0  # clamped


def test_runtime_override_invalid_kind_falls_back_to_declared():
    rep = build_confidence(
        declared_kind="static_catalog",
        tool_name="x",
        runtime_override={"score": 0.7, "kind": "totally_made_up"},
    )
    assert rep.kind == "static_catalog"
    assert rep.score == 0.7


def test_confidence_report_to_dict_shape():
    rep = ConfidenceReport(
        score=0.91, kind="rag", factors=["top_k=0.91"],
    )
    d = rep.to_dict()
    assert set(d) == {"score", "kind", "factors"}


# ─────────────────────────────────────────────────────────────────────
# Tool registry — Stage 11 adds 3
# ─────────────────────────────────────────────────────────────────────


def test_all_stage11_tools_registered():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    names = set(REGISTRY.names())
    assert _STAGE_11_TOOLS.issubset(names), (
        f"missing: {_STAGE_11_TOOLS - names}"
    )


def test_challenge_design_decision_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("challenge_design_decision")
    assert spec.audit_target_type == "decision_challenge"


def test_compare_alternatives_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("compare_alternatives")
    assert spec.audit_target_type == "alternatives_compared"


def test_explain_decision_is_read_only():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("explain_decision")
    assert spec.audit_target_type is None


def test_total_tool_count_at_least_81_after_stage11():
    """Stage 10 (78) + Stage 11 (3) = 81."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 81


# ─────────────────────────────────────────────────────────────────────
# Decorator-time validation
# ─────────────────────────────────────────────────────────────────────


def test_tool_decorator_rejects_unknown_confidence_kind():
    """Typos in confidence_kind fail at decoration time, not at
    runtime. Lock that contract."""
    from pydantic import BaseModel

    from app.agents.tool import ToolContext, tool

    class _In(BaseModel):
        x: int = 0

    class _Out(BaseModel):
        y: int = 0

    with pytest.raises(ValueError, match="confidence_kind"):
        @tool(name="bad_tool_kind_typo", confidence_kind="totally_wrong")
        async def _bad(ctx: ToolContext, input: _In) -> _Out:  # noqa: ARG001
            return _Out()


# ─────────────────────────────────────────────────────────────────────
# Stage 11 retrofit completeness — all 78 prior tools have a kind
# ─────────────────────────────────────────────────────────────────────


def test_all_registered_tools_have_resolvable_confidence_kind():
    """No tool falls into 'unknown'. Either declared on decorator
    or curated in _DEFAULT_KIND_BY_TOOL."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    unresolved = []
    for spec in REGISTRY.specs():
        if spec.confidence_kind is not None:
            continue
        if kind_for_tool(spec.name) == "unknown":
            unresolved.append(spec.name)
    assert not unresolved, (
        f"tools without resolvable confidence kind: {unresolved}"
    )


# ─────────────────────────────────────────────────────────────────────
# compare_alternatives — input invariants
# ─────────────────────────────────────────────────────────────────────


def test_compare_alternatives_requires_at_least_two_options():
    from app.agents.tools.transparency import (
        AlternativeOption,
        CompareAlternativesInput,
        RankedAlternative,
    )

    with pytest.raises(Exception):
        CompareAlternativesInput(
            decision_question="pick one",
            alternatives=[AlternativeOption(name="solo")],
            evaluation_criteria=["cost"],
            ranked=[
                RankedAlternative(name="solo", composite_score=1.0),
            ],
        )


def test_compare_alternatives_rejects_single_ranked():
    from app.agents.tools.transparency import (
        AlternativeOption,
        CompareAlternativesInput,
        RankedAlternative,
    )

    # Two alternatives but only one ranked entry — the model
    # validator caps ranked at min_length=2 too.
    with pytest.raises(Exception):
        CompareAlternativesInput(
            decision_question="pick one",
            alternatives=[
                AlternativeOption(name="a"), AlternativeOption(name="b"),
            ],
            evaluation_criteria=["cost"],
            ranked=[RankedAlternative(name="a", composite_score=1.0)],
        )


# ─────────────────────────────────────────────────────────────────────
# challenge resolution enum
# ─────────────────────────────────────────────────────────────────────


def test_challenge_input_validates_resolution_enum():
    from app.agents.tools.transparency import ChallengeDesignDecisionInput

    # Valid resolutions pass.
    for res in ("rejected_challenge", "decision_revised", "accepted_override"):
        ChallengeDesignDecisionInput(
            decision_id="d-1",
            challenge_text="long enough text here",
            resolution=res,
            response_reasoning="agent reasoning",
        )

    # Invalid resolution fails.
    with pytest.raises(Exception):
        ChallengeDesignDecisionInput(
            decision_id="d-1",
            challenge_text="long enough text here",
            resolution="totally_made_up_state",
        )

    # No resolution means pending — that's allowed.
    ChallengeDesignDecisionInput(
        decision_id="d-1",
        challenge_text="long enough text here",
    )
