"""Building-code lookup tools (Stage 4A).

Wraps Stage 3E ``codes_lookup`` helpers — NBC India compliance,
international IECC envelope, climate-zone design rules, structural
span checks. All read-only.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import codes_lookup as cl


# ─────────────────────────────────────────────────────────────────────
# check_room_against_nbc
# ─────────────────────────────────────────────────────────────────────


class CheckRoomAgainstNBCInput(BaseModel):
    room_type: str = Field(
        description=(
            "Room category — bedroom | living_room | dining_room | study | "
            "kitchen | bathroom. Habitable rooms are validated against "
            "NBC Part 3 minimum-room-dimensions; kitchen/bathroom against "
            "their specific minima."
        ),
        max_length=40,
    )
    area_m2: float = Field(ge=0, le=10000)
    short_side_m: float = Field(ge=0, le=200)
    height_m: float = Field(ge=0, le=20)
    jurisdiction: str = Field(default="india_nbc")


class NBCViolation(BaseModel):
    code: str = Field(description="NBC clause cited, e.g. 'NBC Part 3'.")
    issue: str


class CheckRoomAgainstNBCOutput(BaseModel):
    issues: list[NBCViolation]
    """Empty list = compliant."""
    issue_count: int


@tool(
    name="check_room_against_nbc",
    description=(
        "Run a full NBC India minimum-room-dimensions compliance check "
        "in one call. Returns every violation with the cited part. "
        "Use this whenever discussing whether a room meets code — "
        "covers area, short-side, and ceiling height in one shot."
    ),
    timeout_seconds=10.0,
)
async def check_room_against_nbc_tool(
    ctx: ToolContext,
    input: CheckRoomAgainstNBCInput,
) -> CheckRoomAgainstNBCOutput:
    issues = await cl.check_room_against_nbc(
        ctx.session,
        room_type=input.room_type,
        area_m2=input.area_m2,
        short_side_m=input.short_side_m,
        height_m=input.height_m,
        jurisdiction=input.jurisdiction,
    )
    return CheckRoomAgainstNBCOutput(
        issues=[NBCViolation(**i) for i in issues],
        issue_count=len(issues),
    )


# ─────────────────────────────────────────────────────────────────────
# get_iecc_envelope
# ─────────────────────────────────────────────────────────────────────


class GetIECCEnvelopeInput(BaseModel):
    climate_zone: str = Field(
        description=(
            "IECC climate-zone slug. One of: climate_zone_1_tropical, "
            "climate_zone_2_hot, climate_zone_3_warm, climate_zone_4_mixed, "
            "climate_zone_5_cool, climate_zone_6_cold, climate_zone_7_very_cold."
        ),
        max_length=64,
    )


class GetIECCEnvelopeOutput(BaseModel):
    found: bool
    climate_zone: str
    wall_u_value_w_m2k: Optional[float] = None
    roof_u_value_w_m2k: Optional[float] = None


@tool(
    name="get_iecc_envelope",
    description=(
        "Return the IECC envelope U-value targets (W/m²K) for walls and "
        "roof at a given climate zone. Use when discussing thermal "
        "performance, glazing decisions, or international energy code "
        "compliance."
    ),
    timeout_seconds=8.0,
)
async def get_iecc_envelope_tool(
    ctx: ToolContext,
    input: GetIECCEnvelopeInput,
) -> GetIECCEnvelopeOutput:
    data = await cl.get_iecc_envelope(ctx.session, input.climate_zone)
    if data is None:
        return GetIECCEnvelopeOutput(
            found=False, climate_zone=input.climate_zone
        )
    return GetIECCEnvelopeOutput(
        found=True,
        climate_zone=input.climate_zone,
        wall_u_value_w_m2k=float(data["wall"]),
        roof_u_value_w_m2k=float(data["roof"]),
    )


# ─────────────────────────────────────────────────────────────────────
# lookup_climate_zone
# ─────────────────────────────────────────────────────────────────────


class LookupClimateZoneInput(BaseModel):
    zone: str = Field(
        description=(
            "NBC India climate zone slug. One of: hot_dry, warm_humid, "
            "composite, temperate, cold. Alias-tolerant — accepts "
            "'Hot-Dry', 'HOT DRY', etc."
        ),
        max_length=40,
    )


class LookupClimateZoneOutput(BaseModel):
    found: bool
    zone: str
    pack: Optional[dict[str, Any]] = None
    """Full design strategy: orientation, glazing, wall/roof targets,
    HVAC approach, passive priorities."""


@tool(
    name="lookup_climate_zone",
    description=(
        "Fetch the NBC India climate-zone design strategy (orientation, "
        "glazing strategy, wall + roof U-targets, HVAC approach, passive "
        "priorities). Use whenever the project location's climate would "
        "shape design choices — Bangalore (temperate) needs different "
        "rules than Jaipur (hot_dry) or Mumbai (warm_humid)."
    ),
    timeout_seconds=8.0,
)
async def lookup_climate_zone_tool(
    ctx: ToolContext,
    input: LookupClimateZoneInput,
) -> LookupClimateZoneOutput:
    pack = await cl.get_climate_zone(ctx.session, input.zone)
    return LookupClimateZoneOutput(
        found=pack is not None,
        zone=input.zone,
        pack=pack,
    )


# ─────────────────────────────────────────────────────────────────────
# check_structural_span
# ─────────────────────────────────────────────────────────────────────


class CheckStructuralSpanInput(BaseModel):
    material: str = Field(
        description=(
            "Structural material slug. One of: timber_beam, "
            "engineered_wood_glulam, steel_i_beam, rcc_beam, "
            "rcc_prestressed, rcc_flat_slab, one_way_slab, two_way_slab."
        ),
        max_length=64,
    )
    span_m: float = Field(ge=0, le=100)


class CheckStructuralSpanOutput(BaseModel):
    status: str = Field(description="ok | warn_high | unknown")
    message: str


@tool(
    name="check_structural_span",
    description=(
        "Sanity-check a proposed span (in metres) against typical "
        "limits for the material (IS 456 / IS 800 / IS 883 ranges). "
        "Returns 'warn_high' when the span exceeds typical max — useful "
        "for early-stage feasibility checks before structural sizing."
    ),
    timeout_seconds=8.0,
)
async def check_structural_span_tool(
    ctx: ToolContext,
    input: CheckStructuralSpanInput,
) -> CheckStructuralSpanOutput:
    result = await cl.check_span(
        ctx.session, material=input.material, span_m=input.span_m
    )
    return CheckStructuralSpanOutput(
        status=result["status"],
        message=result["message"],
    )
