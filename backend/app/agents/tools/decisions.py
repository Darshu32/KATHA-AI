"""Stage 8 agent tools — design-decision log.

Two tools:

- :func:`record_design_decision` — write a structured decision row
  for the current project. Audit-target ``design_decision``.
- :func:`recall_design_decisions` — read decisions for the current
  project, optionally filtered by category / version / search query.

Both are project-scoped via ``ctx.project_id``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.repositories.decisions import DesignDecisionRepository

logger = logging.getLogger(__name__)


_KNOWN_CATEGORIES = {
    "material",
    "layout",
    "budget",
    "theme",
    "mep",
    "structural",
    "lighting",
    "general",
}


def _require_project(ctx: ToolContext) -> str:
    if not ctx.project_id:
        raise ToolError(
            "No project_id on the agent context. Decision tools "
            "require a project scope."
        )
    return ctx.project_id


# ─────────────────────────────────────────────────────────────────────
# 1. record_design_decision
# ─────────────────────────────────────────────────────────────────────


class ReasoningStep(BaseModel):
    """One step in the agent's reasoning chain (Stage 11)."""

    step: str = Field(
        max_length=200,
        description="Short label — 'check_budget', 'verify_NBC_clearance'.",
    )
    observation: str = Field(
        max_length=1500,
        description="What the agent observed at this step.",
    )
    conclusion: str = Field(
        max_length=1500,
        description="What the agent concluded from the observation.",
    )


class RecordDecisionInput(BaseModel):
    title: str = Field(
        description=(
            "Short label — 'Picked walnut for island', 'Bumped budget "
            "20% for premium hardware'. Surfaces in recall lists."
        ),
        min_length=3,
        max_length=200,
    )
    summary: str = Field(
        description=(
            "One-paragraph statement of what was decided. The 'what' — "
            "the 'why' goes in `rationale`."
        ),
        min_length=8,
        max_length=2000,
    )
    rationale: str = Field(
        default="",
        max_length=4000,
        description=(
            "Why this decision was made. Cite tool outputs, RAG hits, "
            "client preferences, code requirements."
        ),
    )
    category: str = Field(
        default="general",
        description=(
            "One of: material | layout | budget | theme | mep | "
            "structural | lighting | general."
        ),
        max_length=64,
    )
    version: int = Field(
        default=0,
        ge=0,
        description=(
            "Design-graph version this decision pertains to. 0 when "
            "pre-version (e.g. brief stage)."
        ),
    )
    rejected_alternatives: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Optional list of alternatives considered. Each entry is "
            "free-form: {'option': 'oak', 'reason_rejected': '...'}."
        ),
    )
    sources: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Provenance — strings like 'nbc_india_2016#§3.2', "
            "'pricing_snapshot:abc123', 'cost_engine:tool_call_id'."
        ),
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional free-form tags ('accessibility', 'client_request').",
    )

    # ── Stage 11 — reasoning transparency ────────────────────────────
    reasoning_steps: list[ReasoningStep] = Field(
        default_factory=list,
        max_length=30,
        description=(
            "Ordered reasoning chain. Each step is "
            "{step, observation, conclusion}. The architect walks "
            "this back when they ask 'why did we pick X'. "
            "Empty list is allowed for trivial choices but strongly "
            "discouraged for material / budget / layout decisions."
        ),
    )
    confidence_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "0..1 confidence in the decision. Set high when sources "
            "+ math agree; lower when the LLM had to weigh "
            "competing signals. Null when not measured."
        ),
    )
    confidence_factors: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Human-readable contributors to the confidence score — "
            "['nbc_compliance_verified', 'cost_within_budget', "
            "'theme_pack_match']."
        ),
    )


class DecisionRecord(BaseModel):
    id: str
    project_id: str
    actor_id: Optional[str] = None
    version: int
    category: str
    title: str
    summary: str
    rationale: str = ""
    rejected_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    # Stage 11 — reasoning transparency.
    reasoning_steps: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: Optional[float] = None
    confidence_factors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RecordDecisionOutput(BaseModel):
    decision: DecisionRecord


def _row_to_record(row) -> DecisionRecord:
    created = getattr(row, "created_at", None)
    confidence_score = getattr(row, "confidence_score", None)
    return DecisionRecord(
        id=str(getattr(row, "id", "") or ""),
        project_id=str(getattr(row, "project_id", "") or ""),
        actor_id=getattr(row, "actor_id", None),
        version=int(getattr(row, "version", 0) or 0),
        category=str(getattr(row, "category", "general") or "general"),
        title=str(getattr(row, "title", "") or ""),
        summary=str(getattr(row, "summary", "") or ""),
        rationale=str(getattr(row, "rationale", "") or ""),
        rejected_alternatives=list(getattr(row, "rejected_alternatives", None) or []),
        sources=list(getattr(row, "sources", None) or []),
        tags=list(getattr(row, "tags", None) or []),
        created_at=created.isoformat() if hasattr(created, "isoformat") else None,
        reasoning_steps=list(getattr(row, "reasoning_steps", None) or []),
        confidence_score=(
            float(confidence_score) if confidence_score is not None else None
        ),
        confidence_factors=list(getattr(row, "confidence_factors", None) or []),
        provenance=dict(getattr(row, "provenance", None) or {}),
    )


@tool(
    name="record_design_decision",
    description=(
        "Append a structured design decision to the current project's "
        "decision log. Use whenever you make a non-obvious choice that "
        "the architect (or future-you) will want to recall — material "
        "picks, layout calls, budget shifts, theme switches. Cite "
        "evidence in `sources` (tool ids, RAG hits, client requests) "
        "and rejected alternatives. Append-only — to revise a "
        "decision, record a NEW one that supersedes the prior."
    ),
    timeout_seconds=15.0,
    audit_target_type="design_decision",
)
async def record_design_decision(
    ctx: ToolContext,
    input: RecordDecisionInput,
) -> RecordDecisionOutput:
    project_id = _require_project(ctx)

    category = (input.category or "general").strip().lower()
    if category not in _KNOWN_CATEGORIES:
        raise ToolError(
            f"Unknown category {category!r}. Allowed: "
            f"{sorted(_KNOWN_CATEGORIES)}"
        )

    # Stage 11 — capture provenance + reasoning at write time.
    from app.provenance import build_banner

    provenance = build_banner(
        tool="record_design_decision",
        tool_invocation_kind="agent_call",
        request_id=ctx.request_id,
        extra={"category": category, "version": int(input.version or 0)},
    )
    reasoning_steps = [s.model_dump(mode="json") for s in input.reasoning_steps]

    row = await DesignDecisionRepository.record(
        ctx.session,
        project_id=project_id,
        actor_id=ctx.actor_id,
        title=input.title,
        summary=input.summary,
        category=category,
        version=int(input.version or 0),
        rationale=input.rationale or "",
        rejected_alternatives=input.rejected_alternatives,
        sources=input.sources,
        tags=input.tags,
        reasoning_steps=reasoning_steps,
        confidence_score=input.confidence_score,
        confidence_factors=list(input.confidence_factors or []),
        provenance=provenance,
    )
    return RecordDecisionOutput(decision=_row_to_record(row))


# ─────────────────────────────────────────────────────────────────────
# 2. recall_design_decisions
# ─────────────────────────────────────────────────────────────────────


class RecallDecisionsInput(BaseModel):
    query: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "Optional free-text search across title + summary + "
            "rationale. Omit to list everything (newest-first)."
        ),
    )
    category: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Optional filter on category — material / layout / budget / "
            "theme / mep / structural / lighting / general."
        ),
    )
    version: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Optional filter on the design-graph version the decision "
            "pertains to."
        ),
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="How many decisions to return. Default 20, cap 100.",
    )


class RecallDecisionsOutput(BaseModel):
    project_id: str
    total_for_project: int
    returned_count: int
    decisions: list[DecisionRecord]


@tool(
    name="recall_design_decisions",
    description=(
        "Recall design decisions from the current project's log. "
        "Use to answer 'why did we pick X', 'what did we decide about "
        "the kitchen island', 'show me all material decisions'. "
        "Free-text search (case-insensitive LIKE), category filter, "
        "and version filter are independent. Read-only."
    ),
    timeout_seconds=15.0,
)
async def recall_design_decisions(
    ctx: ToolContext,
    input: RecallDecisionsInput,
) -> RecallDecisionsOutput:
    project_id = _require_project(ctx)

    if input.query and input.query.strip():
        rows = await DesignDecisionRepository.search_for_project(
            ctx.session,
            project_id=project_id,
            query=input.query,
            limit=input.limit,
        )
        # Apply category / version filters in Python — the search query
        # already returns a small bounded set, so this is cheap.
        if input.category:
            rows = [r for r in rows if r.category == input.category]
        if input.version is not None:
            rows = [r for r in rows if int(r.version or 0) == input.version]
    else:
        rows = await DesignDecisionRepository.list_for_project(
            ctx.session,
            project_id=project_id,
            category=input.category,
            version=input.version,
            limit=input.limit,
        )

    total = await DesignDecisionRepository.count_for_project(
        ctx.session, project_id=project_id,
    )

    return RecallDecisionsOutput(
        project_id=project_id,
        total_for_project=total,
        returned_count=len(rows),
        decisions=[_row_to_record(r) for r in rows],
    )
