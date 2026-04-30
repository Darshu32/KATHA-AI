"""Electrical sizing tools (Stage 4B).

Wraps Stage 3C ``mep_sizing`` electrical helpers — ambient lighting
(fixture count to hit a lux target), circuit count from area + power
density, outlet count from room + perimeter.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import mep_sizing


# ─────────────────────────────────────────────────────────────────────
# size_lighting — composite (fixture count + circuits)
# ─────────────────────────────────────────────────────────────────────


class SizeLightingInput(BaseModel):
    area_m2: float = Field(
        ge=0,
        le=10000,
        description="Floor area in m².",
    )
    lux_target: float = Field(
        ge=0,
        le=5000,
        description=(
            "Target ambient lux level. Common values: 100 (bedroom "
            "general), 150 (living general), 300 (kitchen general / "
            "bedroom reading), 500 (office / kitchen counter), "
            "750 (office task), 1000 (retail display)."
        ),
    )
    fixture_key: str = Field(
        default="led_downlight_18w",
        description=(
            "Luminaire from the BRD catalogue. Common: led_downlight_12w, "
            "led_downlight_18w, led_panel_36w, led_cob_spot_7w, "
            "led_cob_spot_15w, led_pendant_20w, led_undercabinet_8w, "
            "led_wall_sconce_10w, led_vanity_bar_15w, led_strip_per_m_10w."
        ),
        max_length=64,
    )
    use_type: str = Field(
        default="residential",
        description=(
            "Power-density profile for circuit count. One of: residential | "
            "office_general | office_high_tech | retail | restaurant | "
            "server_room."
        ),
        max_length=64,
    )
    jurisdiction: str = Field(default="india_nbc")


class SizeLightingOutput(BaseModel):
    fixture_key: str
    fixture_count: Optional[int] = None
    watts_per_fixture: Optional[int] = None
    total_watts: Optional[int] = None
    total_lumens: Optional[int] = None
    design_lux: Optional[float] = None
    """Effective lux delivered by the chosen fixture count
    (after light-loss-factor 0.8 + maintenance-factor 0.7)."""
    lighting_circuits: Optional[int] = None
    power_density_w_m2: Optional[int] = None
    notes: list[str]


@tool(
    name="size_lighting",
    description=(
        "Compute the number of luminaires needed to hit a lux target "
        "for an area, plus the lighting-circuit count derived from "
        "power density. Light-loss factor 0.8 and maintenance factor "
        "0.7 are folded in. Use whenever a room's lighting is "
        "discussed — covers ambient layer."
    ),
    timeout_seconds=10.0,
)
async def size_lighting(
    ctx: ToolContext,
    input: SizeLightingInput,
) -> SizeLightingOutput:
    notes: list[str] = []

    fixture = await mep_sizing.ambient_fixture_count(
        ctx.session,
        area_m2=input.area_m2,
        lux_target=input.lux_target,
        fixture_key=input.fixture_key,
        jurisdiction=input.jurisdiction,
    )
    fixture_count = None
    watts_per_fixture = None
    total_watts = None
    total_lumens = None
    design_lux = None
    if "error" in fixture:
        notes.append(
            f"Fixture lookup: {fixture['error']} (fixture_key={input.fixture_key!r})"
        )
    else:
        fixture_count = int(fixture["count"])
        watts_per_fixture = int(fixture["watts_per_fixture"])
        total_watts = int(fixture["total_watts"])
        total_lumens = int(fixture["total_lumens"])
        design_lux = float(fixture["lux_design"])

    circuits = await mep_sizing.lighting_circuits(
        ctx.session,
        area_m2=input.area_m2,
        use=input.use_type,
        jurisdiction=input.jurisdiction,
    )

    return SizeLightingOutput(
        fixture_key=input.fixture_key,
        fixture_count=fixture_count,
        watts_per_fixture=watts_per_fixture,
        total_watts=total_watts,
        total_lumens=total_lumens,
        design_lux=design_lux,
        lighting_circuits=int(circuits["lighting_circuits"]),
        power_density_w_m2=int(circuits["density_w_m2"]),
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────
# estimate_outlets — composite (general outlet count + task zones)
# ─────────────────────────────────────────────────────────────────────


class EstimateOutletsInput(BaseModel):
    room_type: str = Field(
        description=(
            "Room category. One of: bedroom | living_room | kitchen | "
            "bathroom | office_general | conference_room | classroom | "
            "restaurant_dining | restaurant_kitchen | retail | hotel_room "
            "| gym."
        ),
        max_length=64,
    )
    perimeter_m: float = Field(
        ge=0,
        le=500,
        description="Room perimeter in metres (sum of wall lengths).",
    )
    jurisdiction: str = Field(default="india_nbc")


class EstimateOutletsOutput(BaseModel):
    room_type: str
    perimeter_m: float
    general_outlets: int
    task_zones: int


@tool(
    name="estimate_outlets",
    description=(
        "Estimate general-outlet count + task-light zones for a room "
        "based on perimeter and room type (BIS/IS 732 + studio "
        "practice). Returns concrete counts the agent can specify in "
        "an electrical brief."
    ),
    timeout_seconds=8.0,
)
async def estimate_outlets(
    ctx: ToolContext,
    input: EstimateOutletsInput,
) -> EstimateOutletsOutput:
    result = await mep_sizing.outlet_estimate(
        ctx.session,
        room_type=input.room_type,
        perimeter_m=input.perimeter_m,
        jurisdiction=input.jurisdiction,
    )
    return EstimateOutletsOutput(
        room_type=input.room_type,
        perimeter_m=input.perimeter_m,
        general_outlets=int(result.get("general_outlets") or 0),
        task_zones=int(result.get("task_zones") or 0),
    )
