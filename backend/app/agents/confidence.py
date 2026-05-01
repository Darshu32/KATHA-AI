"""Stage 11 — confidence resolution for agent tools.

Every tool result returned by :func:`app.agents.tool.call_tool` now
carries a ``confidence`` block. The block has three fields:

- ``score`` — float ∈ [0.0, 1.0]
- ``kind`` — one of the :data:`KINDS` values, describing *why* the
  score has the value it does
- ``factors`` — free-form list of human-readable contributors, e.g.
  ``["deterministic_math", "all_inputs_in_catalogue"]``

Tools opt into kind classification in two ways:

1. **Decorator argument** — passing ``confidence_kind="..."`` to
   :func:`app.agents.tool.tool` declares the kind at registration
   time. The framework reads it on dispatch.
2. **Runtime override** — tools can mutate
   ``ctx.state["confidence_override"]`` before returning. The
   framework picks it up. Use this for tools whose confidence
   depends on the actual run (e.g. RAG retrievers stamping the top
   similarity score; LLM tools stamping their self-reported
   confidence).

If neither is set, the framework falls back to
:data:`_DEFAULT_KIND_BY_TOOL` — a curated map covering the 78
existing tools so the Stage 11 retrofit doesn't require touching
each tool module. The ``unknown`` kind (with score ``None``) is the
last-resort default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────
# Confidence kinds
# ─────────────────────────────────────────────────────────────────────


# Each kind has a default score the framework assigns when the tool
# doesn't provide a runtime override. Scores come from how trustable
# the underlying machinery is:
#
#   deterministic       1.00  Math + lookup, no judgement involved
#   static_catalog      1.00  Read from a vetted seed catalog
#   rag                 0.85  Top-k similarity (overridden at runtime)
#   llm_validated       0.90  LLM output with deterministic re-walk
#                              checks (cost engine, sensitivity, etc.)
#   llm_self_report     None  LLM declares its own confidence; if
#                              missing the runtime sets None
#   llm_unvalidated     0.65  LLM output with no validator pass
#   heuristic           0.75  Rule-based + parametric, no validator
#   io_export           1.00  Deterministic byte production
#   unknown             None  Fallback — caller can't claim a number
#
# These defaults are *intentionally conservative*. Tools that can
# claim higher confidence at runtime should set it explicitly via
# ``ctx.state["confidence_override"]``.

KINDS: tuple[str, ...] = (
    "deterministic",
    "static_catalog",
    "rag",
    "llm_validated",
    "llm_self_report",
    "llm_unvalidated",
    "heuristic",
    "io_export",
    "unknown",
)


_DEFAULT_SCORE_BY_KIND: dict[str, Optional[float]] = {
    "deterministic": 1.00,
    "static_catalog": 1.00,
    "rag": 0.85,
    "llm_validated": 0.90,
    "llm_self_report": None,
    "llm_unvalidated": 0.65,
    "heuristic": 0.75,
    "io_export": 1.00,
    "unknown": None,
}


# ─────────────────────────────────────────────────────────────────────
# Confidence-kind map for the existing 78 tools (Stage 11 retrofit)
# ─────────────────────────────────────────────────────────────────────


# Curated by hand for the 78 tools that exist as of Stage 10. Tools
# added in Stage 11+ should declare ``confidence_kind`` directly on
# their ``@tool`` decorator instead of being added here. Keeping
# this central avoids touching every tool module to retrofit.

_DEFAULT_KIND_BY_TOOL: dict[str, str] = {
    # ── Stage 2 — cost ──────────────────────────────────────────────
    "estimate_project_cost": "llm_validated",

    # ── Stage 4A — themes / clearances / codes / mfg / ergonomics ───
    "themes_lookup": "static_catalog",
    "themes_compatibility": "heuristic",
    "clearance_check": "heuristic",
    "clearance_for": "static_catalog",
    "clearance_lookup": "static_catalog",
    "code_lookup": "static_catalog",
    "code_search": "static_catalog",
    "code_check": "heuristic",
    "code_compliance_summary": "llm_validated",
    "manufacturing_lookup": "static_catalog",
    "manufacturing_check": "heuristic",
    "manufacturing_alternatives": "static_catalog",
    "manufacturing_options": "static_catalog",
    "ergonomic_lookup": "static_catalog",
    "ergonomic_check": "heuristic",

    # ── Stage 4B — MEP ──────────────────────────────────────────────
    "hvac_load_estimate": "deterministic",
    "hvac_zone_layout": "heuristic",
    "electrical_load_estimate": "deterministic",
    "electrical_panel_sizing": "deterministic",
    "plumbing_demand_estimate": "deterministic",
    "plumbing_pipe_sizing": "deterministic",
    "plumbing_fixture_count": "deterministic",
    "mep_cost_breakdown": "llm_validated",

    # ── Stage 4C — cost extensions ──────────────────────────────────
    "compare_cost_scenarios": "llm_validated",
    "cost_sensitivity": "llm_validated",

    # ── Stage 4D — specs (LLM-heavy) ────────────────────────────────
    "generate_material_spec": "llm_validated",
    "generate_manufacturing_spec": "llm_validated",
    "generate_mep_spec": "llm_validated",

    # ── Stage 4E — drawings (LLM authoring + deterministic render) ──
    "plan_view": "llm_validated",
    "elevation_view": "llm_validated",
    "section_view": "llm_validated",
    "detail_sheet": "llm_validated",
    "isometric_view": "llm_validated",

    # ── Stage 4F — diagrams (LLM-authored) ──────────────────────────
    "concept_diagram": "llm_unvalidated",
    "form_diagram": "llm_unvalidated",
    "volumetric_block_diagram": "llm_unvalidated",
    "volumetric_component_diagram": "llm_unvalidated",
    "process_diagram": "llm_unvalidated",
    "solid_void_diagram": "llm_unvalidated",
    "spatial_organism_diagram": "llm_unvalidated",
    "hierarchy_diagram": "llm_unvalidated",

    # ── Stage 4G — pipeline orchestration ───────────────────────────
    "generate_initial_design": "llm_validated",
    "regenerate_with_theme": "llm_validated",
    "edit_design_iteration": "llm_validated",
    "list_design_versions": "static_catalog",
    "validate_design_graph": "deterministic",

    # ── Stage 4H — IO / exports / imports ───────────────────────────
    "list_export_formats": "static_catalog",
    "list_import_formats": "static_catalog",
    "list_export_recipients": "static_catalog",
    "build_spec_bundle_for_current": "deterministic",
    "export_design_bundle": "io_export",
    "parse_import_file": "deterministic",
    "generate_import_manifest": "llm_unvalidated",
    "generate_export_manifest": "llm_unvalidated",

    # ── Stage 5 — recall / memory ───────────────────────────────────
    "retrieve_recent_messages": "deterministic",

    # ── Stage 5B/D — project memory RAG ─────────────────────────────
    "search_project_memory": "rag",
    "index_project_artefact": "deterministic",
    "project_memory_stats": "deterministic",
    "prune_project_memory": "deterministic",

    # ── Stage 6 — global knowledge corpus ───────────────────────────
    "search_knowledge_corpus": "rag",
    "list_knowledge_corpus": "static_catalog",

    # ── Stage 7 — vision / multimodal ───────────────────────────────
    "analyze_image": "llm_unvalidated",
    "analyze_site_photo": "llm_unvalidated",
    "analyze_aesthetic_reference": "llm_unvalidated",
    "analyze_sketch": "llm_unvalidated",
    "digitize_handwritten_dimensions": "llm_unvalidated",

    # ── Stage 8 — decisions + profiles ──────────────────────────────
    "record_design_decision": "deterministic",
    "recall_design_decisions": "deterministic",
    "get_architect_fingerprint": "deterministic",
    "get_client_profile": "deterministic",
    "resume_project_context": "deterministic",

    # ── Stage 9 — haptic export ─────────────────────────────────────
    "export_haptic_payload": "deterministic",

    # ── Stage 10 — BRD closure ──────────────────────────────────────
    "intake_design_brief": "deterministic",
    "brief_to_generation_context": "deterministic",
    "analyze_cost_shock": "llm_validated",
    "quick_recommendations": "heuristic",
    "full_recommendations": "llm_validated",

    # ── Stage 11 — transparency tools (forward-declared) ────────────
    "explain_decision": "deterministic",
    "challenge_design_decision": "deterministic",
    "compare_alternatives": "llm_validated",
}


def kind_for_tool(name: str) -> str:
    """Resolve a tool's confidence kind from the curated map.

    Falls back to ``"unknown"`` when the tool isn't in the map yet
    (new tools are encouraged to declare ``confidence_kind`` on
    their ``@tool`` decorator instead of being added here).
    """
    return _DEFAULT_KIND_BY_TOOL.get(name, "unknown")


# ─────────────────────────────────────────────────────────────────────
# ConfidenceReport — what the framework attaches to every result
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ConfidenceReport:
    """The ``confidence`` block on every tool result envelope."""

    score: Optional[float] = None
    kind: str = "unknown"
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "kind": self.kind,
            "factors": list(self.factors),
        }


def build_confidence(
    *,
    declared_kind: Optional[str],
    tool_name: str,
    runtime_override: Optional[dict[str, Any]] = None,
) -> ConfidenceReport:
    """Resolve the final confidence report for a tool call.

    Resolution order:

    1. If the tool set ``ctx.state["confidence_override"]`` to a
       dict shaped like ``{score, kind?, factors?}``, that takes
       precedence — runtime knowledge of the actual call beats any
       static declaration.
    2. Otherwise, the kind comes from the decorator's
       ``confidence_kind=`` argument (``declared_kind``) if set.
    3. Otherwise, the curated :data:`_DEFAULT_KIND_BY_TOOL` map.
    4. Otherwise, ``"unknown"``.

    The score then comes from :data:`_DEFAULT_SCORE_BY_KIND` for
    that kind, unless the runtime override supplied an explicit
    score.
    """
    # 1. Runtime override wins.
    if runtime_override and isinstance(runtime_override, dict):
        kind = runtime_override.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            kind = declared_kind or kind_for_tool(tool_name)
        score = runtime_override.get("score")
        if not isinstance(score, (int, float)):
            score = _DEFAULT_SCORE_BY_KIND.get(kind)
        else:
            score = max(0.0, min(1.0, float(score)))
        factors_raw = runtime_override.get("factors") or []
        factors = [str(f) for f in factors_raw if isinstance(f, str)]
        return ConfidenceReport(score=score, kind=kind, factors=factors)

    # 2/3/4. Static resolution.
    kind = declared_kind if declared_kind in KINDS else kind_for_tool(tool_name)
    return ConfidenceReport(
        score=_DEFAULT_SCORE_BY_KIND.get(kind),
        kind=kind,
        factors=[f"default_for_{kind}"],
    )


__all__ = [
    "KINDS",
    "ConfidenceReport",
    "build_confidence",
    "kind_for_tool",
]
