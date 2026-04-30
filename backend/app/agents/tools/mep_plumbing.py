"""Plumbing sizing tools (Stage 4B).

Wraps Stage 3C ``mep_sizing`` plumbing helpers. The composite
``summarize_water_supply`` rolls up a fixture list to WSFU + Hunter's
GPM + main pipe size in one call. Primitives (``size_drain_pipe``,
``size_vent_stack``) cover follow-up questions.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import mep_sizing


# ─────────────────────────────────────────────────────────────────────
# summarize_water_supply — composite (WSFU + GPM + main pipe size)
# ─────────────────────────────────────────────────────────────────────


class SummarizeWaterSupplyInput(BaseModel):
    fixtures: list[str] = Field(
        description=(
            "Fixture slugs in the layout. Each entry is one fixture; "
            "duplicate slugs for multiples (e.g. two water_closets → "
            "['water_closet', 'water_closet']). Allowed: water_closet | "
            "urinal | wash_basin | kitchen_sink | shower | bathtub | "
            "floor_drain | washing_machine."
        ),
        min_length=1,
        max_length=200,
    )
    jurisdiction: str = Field(default="india_nbc")


class WaterSupplyFixtureLine(BaseModel):
    fixture: str
    cold: float
    hot: float
    total: float


class SummarizeWaterSupplyOutput(BaseModel):
    fixtures: list[WaterSupplyFixtureLine]
    wsfu_cold: float
    wsfu_hot: float
    wsfu_total: float
    demand_gpm: float
    demand_lpm: float
    supply_main_pipe_size_mm: Optional[int] = None


@tool(
    name="summarize_water_supply",
    description=(
        "Roll up a fixture list to total WSFU (cold + hot + grand "
        "total), probable demand in GPM (via Hunter's curve, "
        "flush-tank table from IPC E103.3), demand in LPM, and the "
        "minimum supply main pipe size. Use this for the water-supply "
        "section of any plumbing plan."
    ),
    timeout_seconds=12.0,
)
async def summarize_water_supply(
    ctx: ToolContext,
    input: SummarizeWaterSupplyInput,
) -> SummarizeWaterSupplyOutput:
    result = await mep_sizing.fixture_water_supply_summary(
        ctx.session,
        fixtures=list(input.fixtures),
        jurisdiction=input.jurisdiction,
    )
    return SummarizeWaterSupplyOutput(
        fixtures=[
            WaterSupplyFixtureLine(
                fixture=row["fixture"],
                cold=float(row["cold"]),
                hot=float(row["hot"]),
                total=float(row["total"]),
            )
            for row in (result.get("fixtures") or [])
        ],
        wsfu_cold=float(result.get("wsfu_cold") or 0.0),
        wsfu_hot=float(result.get("wsfu_hot") or 0.0),
        wsfu_total=float(result.get("wsfu_total") or 0.0),
        demand_gpm=float(result.get("demand_gpm") or 0.0),
        demand_lpm=float(result.get("demand_lpm") or 0.0),
        supply_main_pipe_size_mm=(
            int(result["supply_main_pipe_size_mm"])
            if result.get("supply_main_pipe_size_mm") is not None
            else None
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# size_drain_pipe — primitive (DFU → mm)
# ─────────────────────────────────────────────────────────────────────


class SizeDrainPipeInput(BaseModel):
    total_dfu: int = Field(
        ge=0,
        le=10000,
        description=(
            "Total Drainage Fixture Units served by the pipe. Sum DFU "
            "from the table: water_closet=4, urinal=2, wash_basin=1, "
            "kitchen_sink=2, shower=2, bathtub=2, floor_drain=1, "
            "washing_machine=2."
        ),
    )
    jurisdiction: str = Field(default="india_nbc")


class SizeDrainPipeOutput(BaseModel):
    total_dfu: int
    pipe_size_mm: int
    note: Optional[str] = None


@tool(
    name="size_drain_pipe",
    description=(
        "Pick a drain pipe size (mm) for a given total DFU per IPC / "
        "NBC Part 9. Use after ``summarize_water_supply`` if you need "
        "to drill into drainage routing."
    ),
    timeout_seconds=8.0,
)
async def size_drain_pipe(
    ctx: ToolContext,
    input: SizeDrainPipeInput,
) -> SizeDrainPipeOutput:
    result = await mep_sizing.pipe_size_for_dfu(
        ctx.session,
        total_dfu=input.total_dfu,
        jurisdiction=input.jurisdiction,
    )
    if "error" in result:
        return SizeDrainPipeOutput(
            total_dfu=input.total_dfu,
            pipe_size_mm=0,
            note=str(result["error"]),
        )
    return SizeDrainPipeOutput(
        total_dfu=int(result["total_dfu"]),
        pipe_size_mm=int(result["pipe_size_mm"]),
        note=result.get("note"),
    )


# ─────────────────────────────────────────────────────────────────────
# size_vent_stack — primitive (DFU + length → mm)
# ─────────────────────────────────────────────────────────────────────


class SizeVentStackInput(BaseModel):
    total_dfu: int = Field(
        ge=0,
        le=10000,
        description="Total DFU on the vent stack.",
    )
    developed_length_m: float = Field(
        default=0.0,
        ge=0,
        le=500,
        description=(
            "Maximum developed length of the vent stack in metres "
            "(top to base). 0 if unknown — falls back to chart-only "
            "DFU lookup."
        ),
    )
    jurisdiction: str = Field(default="india_nbc")


class SizeVentStackOutput(BaseModel):
    total_dfu: int
    developed_length_m: float
    vent_size_mm: int
    max_length_m_for_size: Optional[int] = None
    note: Optional[str] = None


@tool(
    name="size_vent_stack",
    description=(
        "Pick a vent-stack diameter for a given DFU + developed length "
        "per IPC 906.1 / NBC Part 9. Returns vent size mm + the max "
        "length the chosen size supports."
    ),
    timeout_seconds=8.0,
)
async def size_vent_stack(
    ctx: ToolContext,
    input: SizeVentStackInput,
) -> SizeVentStackOutput:
    result = await mep_sizing.vent_size_for_dfu(
        ctx.session,
        total_dfu=input.total_dfu,
        developed_length_m=input.developed_length_m,
        jurisdiction=input.jurisdiction,
    )
    if "error" in result:
        return SizeVentStackOutput(
            total_dfu=input.total_dfu,
            developed_length_m=input.developed_length_m,
            vent_size_mm=0,
            note=str(result["error"]),
        )
    return SizeVentStackOutput(
        total_dfu=int(result["total_dfu"]),
        developed_length_m=float(result["developed_length_m"]),
        vent_size_mm=int(result["vent_size_mm"]),
        max_length_m_for_size=(
            int(result["max_length_m_for_size"])
            if result.get("max_length_m_for_size") is not None
            else None
        ),
        note=result.get("note"),
    )
