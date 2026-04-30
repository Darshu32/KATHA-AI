"""Manufacturing lookup tools (Stage 4A).

Wraps Stage 3D ``manufacturing_lookup`` helpers — tolerances, lead
times, joinery + welding specs, QA gates. All read-only.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import manufacturing_lookup as ml


# ─────────────────────────────────────────────────────────────────────
# lookup_tolerance
# ─────────────────────────────────────────────────────────────────────


class LookupToleranceInput(BaseModel):
    category: str = Field(
        description=(
            "Tolerance category. BRD §3A: structural | cosmetic | "
            "material_thickness | hardware_placement. Plus extended "
            "categories: woodworking_precision | woodworking_standard | "
            "metal_structural | metal_cosmetic | upholstery_foam."
        ),
        max_length=64,
    )
    jurisdiction: str = Field(default="india_nbc")


class LookupToleranceOutput(BaseModel):
    found: bool
    category: str
    tolerance_plus_minus_mm: Optional[float] = None


@tool(
    name="lookup_tolerance",
    description=(
        "Fetch the BRD ±mm tolerance for a manufacturing category. Use "
        "whenever a fabricator question hinges on precision (joinery, "
        "weld faces, surface uniformity). Cite the result before "
        "specifying a value to a fabricator."
    ),
    timeout_seconds=8.0,
)
async def lookup_tolerance(
    ctx: ToolContext,
    input: LookupToleranceInput,
) -> LookupToleranceOutput:
    value = await ml.tolerance_for(
        ctx.session, input.category, jurisdiction=input.jurisdiction
    )
    return LookupToleranceOutput(
        found=value is not None,
        category=input.category,
        tolerance_plus_minus_mm=value,
    )


# ─────────────────────────────────────────────────────────────────────
# lookup_lead_time
# ─────────────────────────────────────────────────────────────────────


class LookupLeadTimeInput(BaseModel):
    category: str = Field(
        description=(
            "Manufacturing category. One of: woodworking_furniture, "
            "metal_fabrication, upholstery_post_frame, "
            "custom_cast_hardware, powder_coat_job_shop, veneer_pressing."
        ),
        max_length=64,
    )
    jurisdiction: str = Field(default="india_nbc")


class LookupLeadTimeOutput(BaseModel):
    found: bool
    category: str
    weeks_low: Optional[int] = None
    weeks_high: Optional[int] = None


@tool(
    name="lookup_lead_time",
    description=(
        "Get the typical (weeks_low, weeks_high) lead-time band for a "
        "manufacturing category. Use whenever the user asks 'how long "
        "will this take' or planning a delivery schedule."
    ),
    timeout_seconds=8.0,
)
async def lookup_lead_time(
    ctx: ToolContext,
    input: LookupLeadTimeInput,
) -> LookupLeadTimeOutput:
    band = await ml.lead_time_for(
        ctx.session, input.category, jurisdiction=input.jurisdiction
    )
    if band is None:
        return LookupLeadTimeOutput(found=False, category=input.category)
    weeks_low, weeks_high = band
    return LookupLeadTimeOutput(
        found=True,
        category=input.category,
        weeks_low=weeks_low,
        weeks_high=weeks_high,
    )


# ─────────────────────────────────────────────────────────────────────
# lookup_joinery
# ─────────────────────────────────────────────────────────────────────


class LookupJoineryInput(BaseModel):
    joinery_type: str = Field(
        description=(
            "Joinery type. One of: mortise_tenon | dovetail | "
            "pocket_hole | dowel | biscuit | butt_screw | finger_joint."
        ),
        max_length=40,
    )
    jurisdiction: str = Field(default="india_nbc")


class LookupJoineryOutput(BaseModel):
    found: bool
    joinery_type: str
    spec: Optional[dict[str, Any]] = None
    """Full spec — strength, difficulty, use, tolerance_mm."""


@tool(
    name="lookup_joinery",
    description=(
        "Fetch the BRD joinery spec for a wood-joining method "
        "(strength rating, difficulty, typical use, ±mm tolerance). "
        "Use when discussing furniture construction or specifying "
        "joinery to a fabricator."
    ),
    timeout_seconds=8.0,
)
async def lookup_joinery(
    ctx: ToolContext,
    input: LookupJoineryInput,
) -> LookupJoineryOutput:
    spec = await ml.joinery_lookup(
        ctx.session, input.joinery_type, jurisdiction=input.jurisdiction
    )
    return LookupJoineryOutput(
        found=spec is not None,
        joinery_type=input.joinery_type,
        spec=spec,
    )


# ─────────────────────────────────────────────────────────────────────
# list_qa_gates
# ─────────────────────────────────────────────────────────────────────


class ListQAGatesInput(BaseModel):
    """No parameters — returns the 5 BRD-canonical QA stages in order."""


class QAGate(BaseModel):
    stage: str
    brd_scope: str
    checks: list[str]


class ListQAGatesOutput(BaseModel):
    gates: list[QAGate]


@tool(
    name="list_qa_gates",
    description=(
        "Return the 5 BRD-canonical quality-assurance gates in order: "
        "material_inspection → dimension_verification → "
        "finish_inspection → assembly_check → safety_testing. Each "
        "gate includes its scope + required checks. Use whenever the "
        "user asks about QC or fabrication quality."
    ),
    timeout_seconds=8.0,
)
async def list_qa_gates(
    ctx: ToolContext,
    input: ListQAGatesInput,
) -> ListQAGatesOutput:
    rows = await ml.list_qa_gates(ctx.session)
    return ListQAGatesOutput(
        gates=[
            QAGate(
                stage=r["data"]["stage"],
                brd_scope=r["data"]["brd_scope"],
                checks=list(r["data"].get("checks") or []),
            )
            for r in rows
        ]
    )
