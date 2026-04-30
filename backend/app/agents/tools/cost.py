"""Cost-engine tool — wraps the Stage 1 cost engine for the agent loop.

This is **the** Stage 2 pilot tool. The architect chats:

    "What would my 3BHK villa kitchen cost in Bangalore?"

The agent decides to call ``estimate_project_cost``, which:

1. Builds DB-backed pricing knowledge (versioned, time-bounded).
2. Asks the LLM cost engine for a structured breakdown.
3. Records an immutable :class:`PricingSnapshot` so the numbers
   reproduce later.
4. Returns a compact LLM-friendly summary plus the full breakdown +
   ``pricing_snapshot_id`` for audit.

Every later tool follows this same pattern.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.cost_engine_service import (
    CostEngineError,
    CostEngineRequest,
    generate_cost_engine,
)


# ─────────────────────────────────────────────────────────────────────
# Input
# ─────────────────────────────────────────────────────────────────────


class EstimateProjectCostInput(BaseModel):
    """Inputs the LLM provides when calling the cost engine."""

    piece_name: str = Field(
        description=(
            "Short noun phrase identifying what is being estimated, e.g. "
            "'kitchen island', 'modular wardrobe', 'cafe banquette'. "
            "If the user is asking about a whole project, pass the room name."
        ),
        max_length=160,
    )
    project_name: str = Field(
        default="KATHA Project",
        description="Free-text project name. Use the user's own phrasing if available.",
        max_length=200,
    )
    theme: str = Field(
        default="",
        description=(
            "Style theme slug — modern | mid_century_modern | pedestal | "
            "contemporary | scandinavian | rustic | industrial | minimalist | "
            "traditional | luxe. Empty string if unknown."
        ),
        max_length=64,
    )
    city: str = Field(
        default="",
        description=(
            "City or city slug — e.g. 'mumbai', 'bangalore', 'delhi'. "
            "Drives regional price adjustment via the city_price_index. "
            "Empty string defaults to Tier-1 baseline."
        ),
        max_length=80,
    )
    market_segment: str = Field(
        default="mass_market",
        description="Either 'mass_market' or 'luxury'. Drives the profit-margin band.",
    )
    complexity: str = Field(
        default="moderate",
        description=(
            "Joinery / fabrication complexity — one of "
            "simple | moderate | complex | highly_complex. "
            "Drives the labor-hours band."
        ),
    )
    hardware_piece_count: int = Field(
        default=0,
        ge=0,
        le=2000,
        description="How many hardware pieces (handles, hinges, drawer slides …).",
    )
    parametric_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional dict describing the piece's geometry — overall dims, "
            "material breakdown, joinery counts. The LLM cost engine reads "
            "this to derive material quantities."
        ),
    )
    material_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured material spec sheet (Stage 3B output) when available.",
    )
    manufacturing_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured manufacturing spec (Stage 3C output) when available.",
    )
    snapshot_id: Optional[str] = Field(
        default=None,
        description=(
            "If the user is asking 'what was the cost of X last month?', "
            "pass the previously captured pricing_snapshot_id to replay it. "
            "Otherwise leave null and a fresh snapshot is recorded."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────


class CostSummary(BaseModel):
    """Compact LLM-friendly view of the cost breakdown."""

    total_manufacturing_cost_inr: float
    material_subtotal_inr: float
    labor_subtotal_inr: float
    overhead_subtotal_inr: float
    material_pct: float
    labor_pct: float
    overhead_pct: float
    currency: str = "INR"


class EstimateProjectCostOutput(BaseModel):
    """What the agent sees back from the cost tool.

    Keep ``full_breakdown`` available so a follow-up turn can drill in
    without another LLM call. ``pricing_snapshot_id`` is the audit
    receipt the architect can reference.
    """

    summary: CostSummary
    pricing_snapshot_id: str
    city: Optional[str] = None
    city_price_index: float = 1.0
    assumptions: list[str] = Field(default_factory=list)
    validation_passed: bool
    full_breakdown: dict[str, Any]
    """Full cost-engine JSON for follow-up questions."""


# ─────────────────────────────────────────────────────────────────────
# Tool
# ─────────────────────────────────────────────────────────────────────


@tool(
    name="estimate_project_cost",
    description=(
        "Compute a parametric, BRD-grounded cost breakdown (material + "
        "labor + overhead) for a single piece of furniture or millwork. "
        "Always use this when the user asks about prices, budgets, or "
        '"how much would X cost". Returns a structured breakdown plus a '
        "pricing_snapshot_id for reproducible audit."
    ),
    timeout_seconds=45.0,
    audit_target_type="cost_engine",
)
async def estimate_project_cost(
    ctx: ToolContext,
    input: EstimateProjectCostInput,
) -> EstimateProjectCostOutput:
    req = CostEngineRequest(
        project_name=input.project_name,
        piece_name=input.piece_name,
        theme=input.theme,
        parametric_spec=input.parametric_spec,
        material_spec=input.material_spec,
        manufacturing_spec=input.manufacturing_spec,
        city=input.city,
        market_segment=input.market_segment,
        complexity=input.complexity,
        hardware_piece_count=input.hardware_piece_count,
    )

    try:
        result = await generate_cost_engine(
            req,
            session=ctx.session,
            snapshot_id=input.snapshot_id,
            actor_id=ctx.actor_id,
            project_id=ctx.project_id,
        )
    except CostEngineError as exc:
        # Surface as ToolError so the dispatcher emits a structured
        # error envelope; the agent can recover or surface to the user.
        raise ToolError(str(exc)) from exc

    spec = result.get("cost_engine") or {}
    summary_block = spec.get("summary") or {}
    overhead_block = spec.get("overhead") or {}
    material_block = spec.get("material_cost") or {}
    labor_block = spec.get("labor_cost") or {}
    knowledge = result.get("knowledge") or {}
    project_block = knowledge.get("project") or {}

    summary = CostSummary(
        total_manufacturing_cost_inr=float(spec.get("total_manufacturing_cost_inr") or 0),
        material_subtotal_inr=float(material_block.get("material_subtotal_inr") or 0),
        labor_subtotal_inr=float(labor_block.get("labor_subtotal_inr") or 0),
        overhead_subtotal_inr=float(overhead_block.get("overhead_subtotal_inr") or 0),
        material_pct=float(summary_block.get("material_pct_of_total") or 0),
        labor_pct=float(summary_block.get("labor_pct_of_total") or 0),
        overhead_pct=float(summary_block.get("overhead_pct_of_total") or 0),
    )

    validation = result.get("validation") or {}
    validation_passed = all(
        bool(v)
        for k, v in validation.items()
        if k.startswith("currency_") or k.endswith("_consistent") or k.endswith("_in_band")
        or k.endswith("_in_scope") or k.endswith("_matches") or k.endswith("_present")
        or k.endswith("_to_100")
    )

    return EstimateProjectCostOutput(
        summary=summary,
        pricing_snapshot_id=result.get("pricing_snapshot_id") or "",
        city=result.get("city"),
        city_price_index=float(project_block.get("city_price_index") or 1.0),
        assumptions=list(spec.get("assumptions") or []),
        validation_passed=validation_passed,
        full_breakdown=spec,
    )
