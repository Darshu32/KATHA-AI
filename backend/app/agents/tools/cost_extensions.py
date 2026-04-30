"""Stage 4C — cost extension tools.

Two orchestration tools that wrap Stage 2's
:func:`app.services.cost_engine_service.generate_cost_engine` with
multi-run logic:

- :func:`compare_cost_scenarios` — run 2–4 named scenarios side-by-side
  (each is either a fresh request *or* a previously captured
  ``pricing_snapshot_id`` for replay) and return a comparison matrix
  with deltas vs the first scenario.
- :func:`cost_sensitivity` — take a base request, vary **one** input
  parameter across a list of values (e.g. city, complexity,
  market_segment, hardware_piece_count), and return per-variant totals
  + elasticity.

Why this lives in its own module
--------------------------------
Stage 2's :mod:`app.agents.tools.cost` exposes a single estimate
tool. Sensitivity / scenario-compare are *meta* operations that call
the engine repeatedly with permutations. They share helper logic
(extract a slim summary from each engine result, compute deltas,
preserve every snapshot id for audit), so they cohabit one module.

LLM-cost guardrails
-------------------
Each variant triggers a real cost-engine LLM call unless the
caller supplies a snapshot id. To prevent the agent from
accidentally racking up a $10 query, both tools cap the variant
count (4 for compare, 5 for sensitivity) at the **input schema**
layer — bad LLM input fails before any LLM call goes out.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.agents.tool import ToolContext, ToolError, tool
from app.services.cost_engine_service import (
    CostEngineError,
    CostEngineRequest,
    generate_cost_engine,
)

logger = logging.getLogger(__name__)


# Vocab the LLM is allowed to vary. Keep tight — anything outside this
# would either need a different code path (e.g. "theme") or makes no
# sense as a sensitivity axis ("project_name").
_SENSITIVITY_PARAMS = {
    "city",
    "complexity",
    "market_segment",
    "hardware_piece_count",
    "theme",
}


# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


def _summarise_run(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the slim per-scenario summary out of a generate_cost_engine result.

    Mirrors what :class:`app.agents.tools.cost.CostSummary` does — but
    here we keep it as a plain dict so downstream Pydantic models can
    embed the same shape.
    """
    spec = result.get("cost_engine") or {}
    summary_block = spec.get("summary") or {}
    overhead = spec.get("overhead") or {}
    material = spec.get("material_cost") or {}
    labor = spec.get("labor_cost") or {}
    project_block = (result.get("knowledge") or {}).get("project") or {}

    return {
        "total_manufacturing_cost_inr": float(spec.get("total_manufacturing_cost_inr") or 0),
        "material_subtotal_inr": float(material.get("material_subtotal_inr") or 0),
        "labor_subtotal_inr": float(labor.get("labor_subtotal_inr") or 0),
        "overhead_subtotal_inr": float(overhead.get("overhead_subtotal_inr") or 0),
        "material_pct": float(summary_block.get("material_pct_of_total") or 0),
        "labor_pct": float(summary_block.get("labor_pct_of_total") or 0),
        "overhead_pct": float(summary_block.get("overhead_pct_of_total") or 0),
        "city": result.get("city"),
        "city_price_index": float(project_block.get("city_price_index") or 1.0),
        "currency": "INR",
    }


async def _run_one(
    *,
    req: CostEngineRequest,
    session,
    snapshot_id: Optional[str],
    actor_id: Optional[str],
    project_id: Optional[str],
) -> dict[str, Any]:
    """Run a single cost-engine call and surface engine errors as ToolError."""
    try:
        return await generate_cost_engine(
            req,
            session=session,
            snapshot_id=snapshot_id,
            actor_id=actor_id,
            project_id=project_id,
        )
    except CostEngineError as exc:
        # Bubble up as ToolError so the dispatcher returns a structured
        # error envelope — matches the Stage 2 tool's behaviour.
        raise ToolError(str(exc)) from exc


def _build_request(s: "ScenarioInput") -> CostEngineRequest:
    """Map our scenario input model onto the Stage 2 engine request."""
    return CostEngineRequest(
        project_name=s.project_name,
        piece_name=s.piece_name,
        theme=s.theme,
        parametric_spec=s.parametric_spec,
        material_spec=s.material_spec,
        manufacturing_spec=s.manufacturing_spec,
        city=s.city,
        market_segment=s.market_segment,
        complexity=s.complexity,
        hardware_piece_count=s.hardware_piece_count,
    )


# ─────────────────────────────────────────────────────────────────────
# 1. compare_cost_scenarios
# ─────────────────────────────────────────────────────────────────────


class ScenarioInput(BaseModel):
    """One scenario in a compare-cost-scenarios call.

    Either a fresh request (LLM is invoked) or a replay of a recorded
    ``pricing_snapshot_id`` (no fresh knowledge-build, but still one
    LLM call to re-generate the breakdown against the captured
    knowledge).
    """

    label: str = Field(
        description=(
            "Human-readable scenario label, e.g. 'baseline mass-market' or "
            "'luxury Mumbai variant'. Shown in the comparison table — pick "
            "something concise."
        ),
        max_length=80,
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    city: str = Field(default="", max_length=80)
    market_segment: str = Field(default="mass_market", max_length=32)
    complexity: str = Field(default="moderate", max_length=32)
    hardware_piece_count: int = Field(default=0, ge=0, le=2000)
    parametric_spec: Optional[dict[str, Any]] = None
    material_spec: Optional[dict[str, Any]] = None
    manufacturing_spec: Optional[dict[str, Any]] = None
    snapshot_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional — if set, replays the captured knowledge dict from "
            "a prior run instead of building knowledge fresh. The other "
            "fields still drive the LLM brief."
        ),
    )


class CompareScenariosInput(BaseModel):
    """Run 2–4 cost scenarios side-by-side."""

    scenarios: list[ScenarioInput] = Field(
        description=(
            "Two to four scenarios to evaluate. Order matters — the first "
            "scenario is treated as the baseline; subsequent scenarios "
            "report deltas vs scenario 1."
        ),
        min_length=2,
        max_length=4,
    )

    @field_validator("scenarios")
    @classmethod
    def _labels_unique(cls, scenarios: list[ScenarioInput]) -> list[ScenarioInput]:
        labels = [s.label.strip().lower() for s in scenarios]
        if len(set(labels)) != len(labels):
            raise ValueError("Scenario labels must be unique (case-insensitive).")
        return scenarios


class ScenarioResult(BaseModel):
    """Per-scenario row in the comparison table."""

    label: str
    pricing_snapshot_id: Optional[str] = None
    summary: dict[str, Any]
    delta_vs_baseline_inr: Optional[float] = Field(
        default=None,
        description=(
            "Total minus baseline total. Always 0 for the baseline. "
            "Positive means more expensive than baseline."
        ),
    )
    delta_vs_baseline_pct: Optional[float] = None
    error: Optional[str] = Field(
        default=None,
        description=(
            "Set when this scenario could not be priced (e.g. LLM "
            "fallback triggered). Other scenarios still appear so the "
            "comparison is partial-but-useful."
        ),
    )


class CompareScenariosOutput(BaseModel):
    baseline_label: str
    scenarios: list[ScenarioResult]
    cheapest_label: Optional[str] = None
    most_expensive_label: Optional[str] = None
    spread_inr: Optional[float] = Field(
        default=None,
        description="Most expensive minus cheapest among priced scenarios.",
    )
    notes: list[str] = Field(default_factory=list)


@tool(
    name="compare_cost_scenarios",
    description=(
        "Run 2–4 cost-engine scenarios side-by-side and return a "
        "comparison matrix with deltas vs the first scenario. Use this "
        'when the user asks "what if we did X vs Y" for budgets — e.g. '
        "mass-market vs luxury, Mumbai vs Bangalore, simple vs complex "
        "joinery. Each scenario triggers one LLM cost call; cap is 4."
    ),
    timeout_seconds=180.0,  # 4 × 45s engine timeout headroom
    audit_target_type="cost_engine",
)
async def compare_cost_scenarios(
    ctx: ToolContext,
    input: CompareScenariosInput,
) -> CompareScenariosOutput:
    """Run the scenarios concurrently and stitch a comparison."""

    async def _eval(s: ScenarioInput) -> ScenarioResult:
        try:
            result = await _run_one(
                req=_build_request(s),
                session=ctx.session,
                snapshot_id=s.snapshot_id,
                actor_id=ctx.actor_id,
                project_id=ctx.project_id,
            )
        except ToolError as exc:
            return ScenarioResult(
                label=s.label,
                summary={},
                pricing_snapshot_id=None,
                delta_vs_baseline_inr=None,
                delta_vs_baseline_pct=None,
                error=str(exc),
            )
        return ScenarioResult(
            label=s.label,
            pricing_snapshot_id=result.get("pricing_snapshot_id") or "",
            summary=_summarise_run(result),
        )

    # NOTE: each call writes its own pricing_snapshot row, but they all
    # share the same AsyncSession. SQLAlchemy is fine with serial
    # awaits on one session, but parallel writes on the *same* session
    # are unsafe. So we serialise — accept the latency hit.
    rows: list[ScenarioResult] = []
    for scenario in input.scenarios:
        rows.append(await _eval(scenario))

    # Compute deltas vs baseline (first row).
    baseline = rows[0]
    notes: list[str] = []

    if baseline.error or not baseline.summary:
        notes.append(
            f"Baseline scenario '{baseline.label}' could not be priced; "
            "other scenarios are reported in absolute terms only."
        )
        baseline_total: Optional[float] = None
    else:
        baseline_total = float(baseline.summary.get("total_manufacturing_cost_inr") or 0)
        baseline.delta_vs_baseline_inr = 0.0
        baseline.delta_vs_baseline_pct = 0.0

    for row in rows[1:]:
        if row.error or not row.summary:
            continue
        if baseline_total is None or baseline_total == 0:
            continue
        total = float(row.summary.get("total_manufacturing_cost_inr") or 0)
        row.delta_vs_baseline_inr = round(total - baseline_total, 2)
        row.delta_vs_baseline_pct = round(
            (total - baseline_total) / baseline_total * 100.0, 2
        )

    # Cheapest / most expensive across priced rows.
    priced = [
        r for r in rows
        if not r.error and float(r.summary.get("total_manufacturing_cost_inr") or 0) > 0
    ]
    cheapest_label: Optional[str] = None
    most_expensive_label: Optional[str] = None
    spread_inr: Optional[float] = None
    if priced:
        priced_sorted = sorted(
            priced,
            key=lambda r: float(r.summary.get("total_manufacturing_cost_inr") or 0),
        )
        cheapest_label = priced_sorted[0].label
        most_expensive_label = priced_sorted[-1].label
        spread_inr = round(
            float(priced_sorted[-1].summary.get("total_manufacturing_cost_inr") or 0)
            - float(priced_sorted[0].summary.get("total_manufacturing_cost_inr") or 0),
            2,
        )

    failed = [r.label for r in rows if r.error]
    if failed:
        notes.append(
            f"{len(failed)} of {len(rows)} scenarios failed to price: "
            f"{', '.join(failed)}."
        )

    return CompareScenariosOutput(
        baseline_label=baseline.label,
        scenarios=rows,
        cheapest_label=cheapest_label,
        most_expensive_label=most_expensive_label,
        spread_inr=spread_inr,
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. cost_sensitivity
# ─────────────────────────────────────────────────────────────────────


class CostSensitivityInput(BaseModel):
    """Vary one parameter on a base request and report cost elasticity."""

    base: ScenarioInput = Field(
        description=(
            "Base scenario. Every variant overrides exactly one field "
            "of this base; everything else is held constant."
        ),
    )
    parameter: str = Field(
        description=(
            "Which input to vary. One of: 'city', 'complexity', "
            "'market_segment', 'hardware_piece_count', 'theme'."
        ),
    )
    values: list[Any] = Field(
        description=(
            "Two to five values to substitute into the parameter. "
            "Strings for city/complexity/market_segment/theme, integers "
            "for hardware_piece_count."
        ),
        min_length=2,
        max_length=5,
    )

    @field_validator("parameter")
    @classmethod
    def _known_parameter(cls, v: str) -> str:
        if v not in _SENSITIVITY_PARAMS:
            raise ValueError(
                f"parameter must be one of {sorted(_SENSITIVITY_PARAMS)}; got {v!r}"
            )
        return v

    @field_validator("values")
    @classmethod
    def _values_unique(cls, vs: list[Any]) -> list[Any]:
        # Compare by string repr to handle mixed numeric/str harmlessly.
        keys = [str(v).strip().lower() for v in vs]
        if len(set(keys)) != len(keys):
            raise ValueError("Sensitivity values must be unique.")
        return vs


class SensitivityVariant(BaseModel):
    parameter_value: Any
    label: str = Field(description="Human-readable label for the variant row.")
    pricing_snapshot_id: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)
    delta_vs_base_inr: Optional[float] = None
    delta_vs_base_pct: Optional[float] = None
    error: Optional[str] = None


class CostSensitivityOutput(BaseModel):
    parameter: str
    base_summary: dict[str, Any]
    base_pricing_snapshot_id: Optional[str] = None
    variants: list[SensitivityVariant]
    elasticity_pct_per_unit: Optional[float] = Field(
        default=None,
        description=(
            "For numeric parameters only (hardware_piece_count): "
            "average cost change in % per unit of parameter change "
            "vs the base value. Null for categorical parameters."
        ),
    )
    notes: list[str] = Field(default_factory=list)


def _apply_override(base: ScenarioInput, parameter: str, value: Any) -> ScenarioInput:
    """Return a deep-ish copy of ``base`` with one field replaced."""
    data = base.model_dump()
    if parameter == "hardware_piece_count":
        try:
            data[parameter] = int(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                f"hardware_piece_count variant must be an integer, got {value!r}"
            ) from exc
    else:
        data[parameter] = str(value)
    # Differentiate the variant's snapshot from the base — drop replay
    # so each variant captures its own knowledge slice.
    data["snapshot_id"] = None
    # Tag the label so downstream dashboards can group.
    data["label"] = f"{base.label} | {parameter}={value}"
    return ScenarioInput(**data)


@tool(
    name="cost_sensitivity",
    description=(
        "Hold a base cost-engine request constant and vary one input "
        '("what if the city were Mumbai? what if hardware count doubled?") '
        "across 2–5 values, returning cost deltas + elasticity. Use when "
        "the user asks how sensitive the budget is to a single dimension. "
        "Each variant runs the LLM cost engine; cap is 5."
    ),
    timeout_seconds=240.0,  # 5 × 45s engine timeout + base
    audit_target_type="cost_engine",
)
async def cost_sensitivity(
    ctx: ToolContext,
    input: CostSensitivityInput,
) -> CostSensitivityOutput:
    notes: list[str] = []

    # Run base once.
    try:
        base_result = await _run_one(
            req=_build_request(input.base),
            session=ctx.session,
            snapshot_id=input.base.snapshot_id,
            actor_id=ctx.actor_id,
            project_id=ctx.project_id,
        )
    except ToolError as exc:
        # Without a base we cannot compute deltas — surface as a
        # structured error envelope.
        raise ToolError(f"Base scenario could not be priced: {exc}") from exc

    base_summary = _summarise_run(base_result)
    base_total = float(base_summary.get("total_manufacturing_cost_inr") or 0)
    base_snapshot = base_result.get("pricing_snapshot_id") or ""

    # Run each variant serially (shared AsyncSession — see compare_cost_scenarios).
    variants: list[SensitivityVariant] = []
    for value in input.values:
        try:
            variant_req = _apply_override(input.base, input.parameter, value)
        except ToolError as exc:
            variants.append(
                SensitivityVariant(
                    parameter_value=value,
                    label=f"{input.parameter}={value}",
                    error=str(exc),
                )
            )
            continue

        try:
            res = await _run_one(
                req=_build_request(variant_req),
                session=ctx.session,
                snapshot_id=None,
                actor_id=ctx.actor_id,
                project_id=ctx.project_id,
            )
        except ToolError as exc:
            variants.append(
                SensitivityVariant(
                    parameter_value=value,
                    label=variant_req.label,
                    error=str(exc),
                )
            )
            continue

        v_summary = _summarise_run(res)
        v_total = float(v_summary.get("total_manufacturing_cost_inr") or 0)
        delta_inr: Optional[float] = None
        delta_pct: Optional[float] = None
        if base_total > 0:
            delta_inr = round(v_total - base_total, 2)
            delta_pct = round((v_total - base_total) / base_total * 100.0, 2)

        variants.append(
            SensitivityVariant(
                parameter_value=value,
                label=variant_req.label,
                pricing_snapshot_id=res.get("pricing_snapshot_id") or "",
                summary=v_summary,
                delta_vs_base_inr=delta_inr,
                delta_vs_base_pct=delta_pct,
            )
        )

    # Elasticity — only meaningful for numeric parameters.
    elasticity: Optional[float] = None
    if input.parameter == "hardware_piece_count":
        base_value = float(input.base.hardware_piece_count or 0)
        deltas: list[float] = []
        for v in variants:
            if v.error or v.delta_vs_base_pct is None:
                continue
            try:
                vv = float(v.parameter_value)
            except (TypeError, ValueError):
                continue
            if vv == base_value:
                continue
            unit_change = vv - base_value
            if unit_change == 0:
                continue
            deltas.append(v.delta_vs_base_pct / unit_change)
        if deltas:
            elasticity = round(sum(deltas) / len(deltas), 4)

    failed = [v.label for v in variants if v.error]
    if failed:
        notes.append(
            f"{len(failed)} of {len(variants)} variants failed to price: "
            f"{', '.join(failed)}."
        )

    return CostSensitivityOutput(
        parameter=input.parameter,
        base_summary=base_summary,
        base_pricing_snapshot_id=base_snapshot,
        variants=variants,
        elasticity_pct_per_unit=elasticity,
        notes=notes,
    )


# Avoid an unused-import warning when asyncio is only referenced in
# docstrings / doc snippets. _run_one is async, so asyncio is implicitly
# used by the ``await`` chain — keep this for IDE happiness.
_ = asyncio
