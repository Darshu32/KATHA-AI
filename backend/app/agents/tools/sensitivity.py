"""Stage 10 agent tool — Cost sensitivity analysis (BRD §4D).

Wraps :func:`app.services.sensitivity_service.generate_sensitivity_analysis`
so the agent can answer the BRD §4D what-if questions on demand:

    ├── If material +X% → final price increases by [%]
    ├── If labor    +X% → final price increases by [%]
    ├── If overhead +X% → final price increases by [%]
    └── Cost at different volumes (1, 5, 10 pieces by default)

The default shock is **10%** per BRD §4D. The deterministic re-walk
inside :mod:`app.services.sensitivity_service` runs the math; the
LLM narrates the table without inventing numbers.

Distinct from :mod:`app.agents.tools.cost_extensions`:

- ``cost_extensions.cost_sensitivity`` varies a single *input
  parameter* (city, complexity, market_segment) across a list — it
  re-runs the whole cost engine per variant.
- ``cost_extensions.compare_cost_scenarios`` runs 2–4 named
  scenarios side-by-side.
- This tool (``analyze_cost_shock``) shocks one of *material /
  labor / overhead* by ±X% and re-walks the price stack
  deterministically. Cheaper than re-running the engine; this is
  what BRD §4D actually asks for.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.sensitivity_service import (
    DEFAULT_VOLUMES,
    SHOCK_PCT_DEFAULT,
    SensitivityRequest,
    generate_sensitivity_analysis,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# analyze_cost_shock
# ─────────────────────────────────────────────────────────────────────


class AnalyzeCostShockInput(BaseModel):
    project_name: str = Field(
        default="KATHA Project",
        max_length=200,
        description="Display name carried into the report header.",
    )
    piece_name: str = Field(
        default="Primary piece",
        max_length=160,
        description="Which piece this analysis is about.",
    )
    city: str = Field(
        default="",
        max_length=80,
        description=(
            "City context. Affects price-index notes in the report; "
            "does not alter the deterministic math."
        ),
    )
    cost_engine: dict[str, Any] = Field(
        description=(
            "BRD §4A cost_engine spec object. Get it from the "
            "estimate_project_cost tool's output."
        ),
    )
    pricing_buildup: dict[str, Any] = Field(
        description=(
            "BRD §4B pricing_buildup spec object. Includes the "
            "manufacturer / designer / retail margin layers and the "
            "final retail price."
        ),
    )
    shock_pct: float = Field(
        default=SHOCK_PCT_DEFAULT,
        ge=0,
        le=50,
        description=(
            "Shock magnitude in percent. Defaults to 10.0 per BRD §4D. "
            "Cap 50%."
        ),
    )
    volumes: list[int] = Field(
        default_factory=lambda: list(DEFAULT_VOLUMES),
        description=(
            "Volume scenarios (units). Default [1, 5, 10] per BRD §4D. "
            "Each volume re-walks the manufacturer-margin stack at the "
            "tier that volume falls into (one_off / small_batch / "
            "production / mass_production)."
        ),
    )


class AnalyzeCostShockOutput(BaseModel):
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Slim block with shock_pct + volumes used + per-component "
            "uplift percentages — easy for the agent to narrate."
        ),
    )
    sensitivity_analysis: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Full BRD §4D report — material / labor / overhead shock "
            "rows, volume rows, narrative, validation block. Hand "
            "this to the user when they ask for the full picture."
        ),
    )


def _summarise(spec: dict[str, Any], req: SensitivityRequest) -> dict[str, Any]:
    """Pull the key uplift numbers out of the full spec."""
    rows: list[dict[str, Any]] = list(spec.get("shock_table") or [])
    by_component: dict[str, dict[str, Any]] = {}
    for row in rows:
        comp = (row.get("shocked_component") or "").lower()
        if comp:
            by_component[comp] = {
                "uplift_pct": row.get("final_price_uplift_pct"),
                "shocked_final_inr": row.get("shocked_final_retail_price_inr"),
            }
    volume_rows = list(spec.get("volume_table") or [])
    volume_summary = [
        {
            "units": v.get("units"),
            "tier": v.get("volume_tier"),
            "final_inr": v.get("final_retail_price_inr"),
            "per_unit_inr": v.get("per_unit_inr"),
        }
        for v in volume_rows
    ]
    return {
        "shock_pct": req.shock_pct,
        "volumes": list(req.volumes),
        "shocks": by_component,
        "volume_table": volume_summary,
    }


@tool(
    name="analyze_cost_shock",
    description=(
        "Run BRD §4D sensitivity analysis on a costed project. Shocks "
        "material / labor / overhead by ±X% (default 10% per BRD) and "
        "re-walks the BRD pricing stack deterministically; also "
        "computes the same project at multiple volumes (default 1, "
        "5, 10 pieces) so the agent can answer 'what happens if "
        "material goes up 10%' or 'how much cheaper at 10 pieces'. "
        "Requires a prior cost_engine + pricing_buildup spec — call "
        "estimate_project_cost first. The deterministic re-walk lives "
        "in the service layer; the LLM narrates the table without "
        "inventing numbers. Audit target cost_sensitivity_analysis."
    ),
    timeout_seconds=90.0,
    audit_target_type="cost_sensitivity_analysis",
)
async def analyze_cost_shock(
    ctx: ToolContext,
    input: AnalyzeCostShockInput,
) -> AnalyzeCostShockOutput:
    try:
        req = SensitivityRequest(
            project_name=input.project_name,
            piece_name=input.piece_name,
            city=input.city,
            cost_engine=dict(input.cost_engine or {}),
            pricing_buildup=dict(input.pricing_buildup or {}),
            shock_pct=float(input.shock_pct),
            volumes=list(input.volumes),
        )
    except Exception as exc:  # noqa: BLE001 — Pydantic chain
        raise ToolError(f"Invalid sensitivity request: {exc}") from exc

    try:
        result = await generate_sensitivity_analysis(req)
    except Exception as exc:  # noqa: BLE001 — surface to LLM
        raise ToolError(
            f"Sensitivity analysis failed: {type(exc).__name__}: {exc}"
        ) from exc

    spec = result.get("sensitivity_analysis") or {}
    return AnalyzeCostShockOutput(
        summary=_summarise(spec, req),
        sensitivity_analysis=spec,
    )
