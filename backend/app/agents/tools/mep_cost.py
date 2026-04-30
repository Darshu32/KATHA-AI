"""MEP system-level cost rollup (Stage 4B).

Wraps Stage 3C ``mep_sizing.system_cost_estimate`` — gives the agent
an early-stage cost band for major MEP systems (HVAC / electrical /
plumbing / fire-fighting / low-voltage) at per-m² rates. Useful for
sanity-checking budgets *before* the cost engine runs a full BOQ.

Distinct from Stage 2's ``estimate_project_cost`` (which prices a
single fabricated piece). This tool answers *"what should I budget
for HVAC across a 1500 m² office?"* in one call.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import mep_sizing


# ─────────────────────────────────────────────────────────────────────
# mep_system_cost_estimate
# ─────────────────────────────────────────────────────────────────────


class MEPSystemCostEstimateInput(BaseModel):
    system_key: str = Field(
        description=(
            "MEP system slug. One of: hvac_split_residential | "
            "hvac_vrf_commercial | hvac_chilled_water_large | "
            "electrical_residential | electrical_commercial | "
            "plumbing_residential | plumbing_commercial | "
            "fire_fighting_residential | fire_fighting_commercial | "
            "low_voltage_commercial."
        ),
        max_length=80,
    )
    area_m2: float = Field(
        ge=0,
        le=1000000,
        description="Floor area to multiply against the per-m² rate band.",
    )
    jurisdiction: str = Field(default="india_nbc")


class MEPCostBand(BaseModel):
    low: float
    high: float


class MEPSystemCostEstimateOutput(BaseModel):
    found: bool
    system: str
    area_m2: float
    rate_inr_m2: Optional[MEPCostBand] = None
    total_inr: Optional[MEPCostBand] = None
    note: Optional[str] = None


@tool(
    name="mep_system_cost_estimate",
    description=(
        "Rough order-of-magnitude cost for a major MEP system across "
        "a floor area (Tier-1 Indian metros, mid-spec). Returns a low "
        "/ high INR band for both the per-m² rate and the total. Use "
        "this for early-stage budget conversations BEFORE the full "
        "cost engine runs. Apply a regional price index on top for "
        "non-Tier-1 cities."
    ),
    timeout_seconds=8.0,
)
async def mep_system_cost_estimate(
    ctx: ToolContext,
    input: MEPSystemCostEstimateInput,
) -> MEPSystemCostEstimateOutput:
    result = await mep_sizing.system_cost_estimate(
        ctx.session,
        system_key=input.system_key,
        area_m2=input.area_m2,
        jurisdiction=input.jurisdiction,
    )
    if "error" in result:
        return MEPSystemCostEstimateOutput(
            found=False,
            system=input.system_key,
            area_m2=input.area_m2,
            note=str(result["error"]),
        )

    rate = result.get("rate_inr_m2") or {}
    total = result.get("total_inr") or {}
    return MEPSystemCostEstimateOutput(
        found=True,
        system=input.system_key,
        area_m2=input.area_m2,
        rate_inr_m2=MEPCostBand(
            low=float(rate.get("low") or 0),
            high=float(rate.get("high") or 0),
        ),
        total_inr=MEPCostBand(
            low=float(total.get("low") or 0),
            high=float(total.get("high") or 0),
        ),
    )
