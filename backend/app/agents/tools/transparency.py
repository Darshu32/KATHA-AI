"""Stage 11 agent tools — reasoning transparency.

Three tools that make the agent's thinking visible and challengeable:

- :func:`explain_decision` — read tool. Returns the full record for
  one decision (reasoning steps, sources, alternatives considered,
  confidence, provenance) plus the chain of any challenges filed
  against it. The architect uses this to interrogate any past
  choice.
- :func:`challenge_design_decision` — write tool. Files a challenge
  against a decision and (optionally) records the agent's
  resolution: ``rejected_challenge`` (agent stands by it),
  ``decision_revised`` (agent agrees, references a new decision),
  or ``accepted_override`` (user overrides without re-reasoning).
- :func:`compare_alternatives` — generic alternatives explorer.
  Given N candidate options against M evaluation criteria, produces
  a ranked comparison and (optionally) auto-records a
  :class:`DesignDecision` capturing the winner *and* the rejected
  alternatives, so the rejection ledger never goes empty.

All three are project-scoped via :attr:`ToolContext.project_id`.
``challenge_design_decision`` and ``compare_alternatives`` write
audit events.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.agents.tool import ToolContext, ToolError, tool
from app.models.orm import DecisionChallenge, DesignDecision
from app.provenance import build_banner
from app.repositories.decisions import (
    DecisionChallengeRepository,
    DesignDecisionRepository,
)

logger = logging.getLogger(__name__)


_RESOLUTIONS = {
    "rejected_challenge",
    "decision_revised",
    "accepted_override",
}


def _require_project(ctx: ToolContext) -> str:
    if not ctx.project_id:
        raise ToolError(
            "No project_id on the agent context. Transparency tools "
            "are project-scoped."
        )
    return ctx.project_id


def _decision_to_dict(row: DesignDecision) -> dict[str, Any]:
    """Same shape as :func:`app.agents.tools.decisions._row_to_record`
    but as a plain dict — keeps this module independent."""
    created = getattr(row, "created_at", None)
    score = getattr(row, "confidence_score", None)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "actor_id": row.actor_id,
        "version": int(row.version or 0),
        "category": row.category or "general",
        "title": row.title or "",
        "summary": row.summary or "",
        "rationale": row.rationale or "",
        "rejected_alternatives": list(row.rejected_alternatives or []),
        "sources": list(row.sources or []),
        "tags": list(row.tags or []),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
        "reasoning_steps": list(getattr(row, "reasoning_steps", None) or []),
        "confidence_score": float(score) if score is not None else None,
        "confidence_factors": list(getattr(row, "confidence_factors", None) or []),
        "provenance": dict(getattr(row, "provenance", None) or {}),
    }


def _challenge_to_dict(row: DecisionChallenge) -> dict[str, Any]:
    created = getattr(row, "created_at", None)
    return {
        "id": str(row.id),
        "decision_id": str(row.decision_id),
        "project_id": str(row.project_id),
        "challenger_id": row.challenger_id,
        "challenge_text": row.challenge_text or "",
        "resolution": row.resolution or "pending",
        "response_reasoning": row.response_reasoning or "",
        "new_decision_id": row.new_decision_id,
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }


# ─────────────────────────────────────────────────────────────────────
# 1. explain_decision
# ─────────────────────────────────────────────────────────────────────


class ExplainDecisionInput(BaseModel):
    decision_id: str = Field(
        max_length=64,
        description=(
            "ID of the DesignDecision to walk back. Look it up via "
            "recall_design_decisions if you only have a fuzzy "
            "reference."
        ),
    )


class ExplainDecisionOutput(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)
    challenges: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


@tool(
    name="explain_decision",
    description=(
        "Walk back a single design decision in full — reasoning "
        "steps, sources cited, alternatives considered, confidence "
        "score + factors, provenance banner, and the chain of any "
        "challenges filed against it. Use when the architect asks "
        "'why did we pick X' or 'show me the math behind decision Y'. "
        "Project-scoped. Read-only."
    ),
    timeout_seconds=15.0,
    confidence_kind="deterministic",
)
async def explain_decision(
    ctx: ToolContext,
    input: ExplainDecisionInput,
) -> ExplainDecisionOutput:
    project_id = _require_project(ctx)

    row = await DesignDecisionRepository.get_by_id(
        ctx.session, decision_id=input.decision_id,
    )
    if row is None or row.project_id != project_id:
        # Cross-project access: same shape as 'not found' — no leak.
        raise ToolError(
            f"Decision {input.decision_id!r} not found in this project."
        )

    challenges = await DecisionChallengeRepository.list_for_decision(
        ctx.session, decision_id=input.decision_id, limit=50,
    )

    decision_dict = _decision_to_dict(row)
    challenge_dicts = [_challenge_to_dict(c) for c in challenges]

    pending = sum(1 for c in challenges if c.resolution == "pending")
    resolved = len(challenges) - pending

    return ExplainDecisionOutput(
        decision=decision_dict,
        challenges=challenge_dicts,
        summary={
            "decision_id": decision_dict["id"],
            "title": decision_dict["title"],
            "category": decision_dict["category"],
            "confidence_score": decision_dict["confidence_score"],
            "reasoning_step_count": len(decision_dict["reasoning_steps"]),
            "rejected_alternative_count": len(
                decision_dict["rejected_alternatives"]
            ),
            "source_count": len(decision_dict["sources"]),
            "challenge_count": len(challenges),
            "pending_challenges": pending,
            "resolved_challenges": resolved,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# 2. challenge_design_decision
# ─────────────────────────────────────────────────────────────────────


class ChallengeDesignDecisionInput(BaseModel):
    decision_id: str = Field(
        max_length=64,
        description="ID of the DesignDecision being challenged.",
    )
    challenge_text: str = Field(
        min_length=4,
        max_length=2000,
        description=(
            "What the challenger objects to. Be specific — 'the cost "
            "estimate ignores the import duty I mentioned in the "
            "brief' beats 'too expensive'."
        ),
    )
    resolution: Optional[str] = Field(
        default=None,
        description=(
            "If the agent already knows the resolution (e.g. it just "
            "re-reasoned during this turn), set it here. One of: "
            "rejected_challenge | decision_revised | accepted_override. "
            "Omit to file the challenge in pending state and resolve "
            "it later."
        ),
    )
    response_reasoning: str = Field(
        default="",
        max_length=4000,
        description=(
            "Agent's reply to the challenge. Required when "
            "resolution is set; ignored otherwise."
        ),
    )
    new_decision_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "When resolution is decision_revised or accepted_override "
            "and a new decision was recorded that supersedes the "
            "original, link it here so the explain tool can walk "
            "the supersession chain."
        ),
    )

    @field_validator("resolution")
    @classmethod
    def _check_resolution(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in _RESOLUTIONS:
            raise ValueError(
                f"resolution must be one of {sorted(_RESOLUTIONS)}; got {v!r}"
            )
        return v


class ChallengeDesignDecisionOutput(BaseModel):
    challenge: dict[str, Any] = Field(default_factory=dict)
    superseded: Optional[dict[str, Any]] = None
    """When resolution links a new_decision_id, the new decision's
    record is embedded here so the agent can show the user the
    revised choice without an extra round-trip."""


@tool(
    name="challenge_design_decision",
    description=(
        "File a challenge against a recorded design decision (Stage "
        "11 transparency). The architect can challenge any past "
        "decision; the agent then re-reasons and emits one of three "
        "resolutions: rejected_challenge (agent stands by the "
        "decision, with reasoning), decision_revised (agent agrees "
        "and a new DesignDecision supersedes the original), or "
        "accepted_override (user overrides without re-reasoning). "
        "If the agent calls this in the same turn as it produces "
        "the resolution, it can pass resolution + response_reasoning "
        "+ new_decision_id atomically. Otherwise the challenge is "
        "filed in pending state. Project-scoped. Audit target "
        "decision_challenge."
    ),
    timeout_seconds=15.0,
    audit_target_type="decision_challenge",
    confidence_kind="deterministic",
)
async def challenge_design_decision(
    ctx: ToolContext,
    input: ChallengeDesignDecisionInput,
) -> ChallengeDesignDecisionOutput:
    project_id = _require_project(ctx)

    target = await DesignDecisionRepository.get_by_id(
        ctx.session, decision_id=input.decision_id,
    )
    if target is None or target.project_id != project_id:
        raise ToolError(
            f"Decision {input.decision_id!r} not found in this project."
        )

    if input.new_decision_id:
        new_target = await DesignDecisionRepository.get_by_id(
            ctx.session, decision_id=input.new_decision_id,
        )
        if new_target is None or new_target.project_id != project_id:
            raise ToolError(
                f"new_decision_id {input.new_decision_id!r} not found "
                "in this project."
            )

    if input.resolution and not input.response_reasoning.strip():
        raise ToolError(
            "response_reasoning is required when resolution is set."
        )

    row = await DecisionChallengeRepository.file_challenge(
        ctx.session,
        project_id=project_id,
        decision_id=input.decision_id,
        challenger_id=ctx.actor_id,
        challenge_text=input.challenge_text,
        extra={"filed_via": "agent_tool"},
    )

    if input.resolution:
        row = await DecisionChallengeRepository.resolve(
            ctx.session,
            challenge_id=row.id,
            resolution=input.resolution,
            response_reasoning=input.response_reasoning,
            new_decision_id=input.new_decision_id,
        )

    superseded: Optional[dict[str, Any]] = None
    if input.new_decision_id:
        new_row = await DesignDecisionRepository.get_by_id(
            ctx.session, decision_id=input.new_decision_id,
        )
        if new_row is not None:
            superseded = _decision_to_dict(new_row)

    return ChallengeDesignDecisionOutput(
        challenge=_challenge_to_dict(row),
        superseded=superseded,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. compare_alternatives
# ─────────────────────────────────────────────────────────────────────


class AlternativeOption(BaseModel):
    name: str = Field(
        max_length=200,
        description="Short label — 'walnut', 'oak', 'rubberwood'.",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form key/values describing the option — "
            "{'cost_inr': 1500, 'lead_weeks': 4, 'theme_match': 'high'}."
        ),
    )


class CriterionScore(BaseModel):
    criterion: str = Field(max_length=120)
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Per-criterion score for this option (0..1).",
    )
    rationale: str = Field(default="", max_length=600)


class RankedAlternative(BaseModel):
    name: str
    composite_score: float = Field(ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)
    per_criterion: list[CriterionScore] = Field(default_factory=list)
    rejected_reason: Optional[str] = None
    """Set on every option except the winner. The agent's
    one-sentence justification for not picking it."""


class CompareAlternativesInput(BaseModel):
    decision_question: str = Field(
        min_length=8,
        max_length=400,
        description=(
            "What's being decided? — 'Pick primary wood for the "
            "kitchen island'. Becomes the title of the recorded "
            "decision."
        ),
    )
    alternatives: list[AlternativeOption] = Field(
        min_length=2,
        max_length=10,
        description=(
            "The candidates to evaluate. At least 2; cap 10. The "
            "agent must produce >=1 rejected alternative for the "
            "rejection ledger to stay non-empty."
        ),
    )
    evaluation_criteria: list[str] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Names of criteria — 'cost', 'theme_match', "
            "'lead_time', 'durability'. Free-form; the agent ranks "
            "options against each."
        ),
    )
    ranked: list[RankedAlternative] = Field(
        min_length=2,
        description=(
            "Pre-computed ranked list. The agent (or upstream tool) "
            "scores each option per criterion, computes composite "
            "scores, and submits the result. The first entry is the "
            "winner."
        ),
    )
    auto_record_decision: bool = Field(
        default=True,
        description=(
            "When True (default) a DesignDecision is auto-recorded "
            "with title=decision_question, summary=winner rationale, "
            "and rejected_alternatives = the runners-up. The "
            "rejection ledger is the point of this tool — disabling "
            "auto-record only makes sense for read-only what-if "
            "exploration."
        ),
    )
    category: str = Field(
        default="general",
        max_length=64,
        description=(
            "Decision category to stamp on the auto-recorded row. "
            "Same enum as record_design_decision."
        ),
    )
    version: int = Field(
        default=0,
        ge=0,
        description="Design-graph version this comparison pertains to.",
    )
    sources: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Provenance citations for the ranking.",
    )
    confidence_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
    )
    confidence_factors: list[str] = Field(
        default_factory=list, max_length=20,
    )


class CompareAlternativesOutput(BaseModel):
    winner: dict[str, Any] = Field(default_factory=dict)
    ranked: list[dict[str, Any]] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    decision_id: Optional[str] = None
    """Set when ``auto_record_decision`` was True — the agent can
    chain into ``explain_decision`` immediately."""


@tool(
    name="compare_alternatives",
    description=(
        "Generic alternatives explorer (Stage 11 BRD asks 'agent "
        "always retains rejected paths'). Given N candidates "
        "scored against M criteria, returns the ranked comparison "
        "and (by default) auto-records a DesignDecision capturing "
        "the winner + every rejected alternative — so the "
        "rejection ledger never goes empty. Use whenever the agent "
        "is about to make a choice between several reasonable "
        "options. Project-scoped. Audit target alternatives_compared."
    ),
    timeout_seconds=20.0,
    audit_target_type="alternatives_compared",
    confidence_kind="llm_validated",
)
async def compare_alternatives(
    ctx: ToolContext,
    input: CompareAlternativesInput,
) -> CompareAlternativesOutput:
    project_id = _require_project(ctx)

    if not input.ranked:
        raise ToolError("ranked must contain at least the winner.")
    if len(input.ranked) != len(input.alternatives):
        raise ToolError(
            f"ranked has {len(input.ranked)} entries but "
            f"alternatives has {len(input.alternatives)} — every "
            "candidate must appear in the ranking."
        )

    # Sort by composite_score descending (defensive — caller should
    # already submit sorted, but lock the invariant here so the
    # winner is always ranked[0]).
    sorted_ranked = sorted(
        input.ranked, key=lambda r: r.composite_score, reverse=True,
    )
    winner = sorted_ranked[0]
    rejected = sorted_ranked[1:]

    # Validate every rejected option has a rejection reason — the
    # whole point of this tool. Silent rejections defeat the
    # rejection ledger.
    missing_reasons = [
        r.name for r in rejected
        if not (r.rejected_reason and r.rejected_reason.strip())
    ]
    if missing_reasons:
        raise ToolError(
            f"Every rejected alternative must include rejected_reason. "
            f"Missing for: {missing_reasons}"
        )

    decision_id: Optional[str] = None
    if input.auto_record_decision:
        rejected_payload = [
            {
                "option": r.name,
                "composite_score": r.composite_score,
                "reason_rejected": r.rejected_reason,
                "properties": dict(r.properties or {}),
                "per_criterion": [
                    s.model_dump(mode="json") for s in r.per_criterion
                ],
            }
            for r in rejected
        ]
        reasoning_steps = [
            {
                "step": f"score_{r.name}",
                "observation": (
                    f"composite={r.composite_score:.3f} across "
                    f"{len(r.per_criterion)} criteria"
                ),
                "conclusion": (
                    "winner" if r is winner
                    else f"rejected — {r.rejected_reason or '(no reason given)'}"
                ),
            }
            for r in sorted_ranked
        ]
        provenance = build_banner(
            tool="compare_alternatives",
            tool_invocation_kind="agent_call",
            request_id=ctx.request_id,
            extra={
                "decision_question": input.decision_question,
                "criteria_count": len(input.evaluation_criteria),
                "candidate_count": len(input.alternatives),
            },
        )
        summary = (
            f"Picked {winner.name} (composite {winner.composite_score:.3f}) "
            f"over {len(rejected)} alternative(s)."
        )
        row = await DesignDecisionRepository.record(
            ctx.session,
            project_id=project_id,
            actor_id=ctx.actor_id,
            title=input.decision_question[:200],
            summary=summary[:2000],
            category=input.category,
            version=int(input.version or 0),
            rationale=(
                f"Ranked {len(input.alternatives)} options against "
                f"{len(input.evaluation_criteria)} criteria "
                f"({', '.join(input.evaluation_criteria)})."
            ),
            rejected_alternatives=rejected_payload,
            sources=list(input.sources or []),
            tags=["alternatives_compared"],
            reasoning_steps=reasoning_steps,
            confidence_score=input.confidence_score,
            confidence_factors=list(input.confidence_factors or []),
            provenance=provenance,
        )
        decision_id = row.id

    return CompareAlternativesOutput(
        winner={
            "name": winner.name,
            "composite_score": winner.composite_score,
            "properties": dict(winner.properties or {}),
            "per_criterion": [
                s.model_dump(mode="json") for s in winner.per_criterion
            ],
        },
        ranked=[r.model_dump(mode="json") for r in sorted_ranked],
        rejected=[r.model_dump(mode="json") for r in rejected],
        decision_id=decision_id,
    )
