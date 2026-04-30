"""Clearance + space-area validation tools (Stage 4A).

Wraps Stage 3B knowledge service helpers. All three return a status
envelope (``ok | warn_low | warn_high | unknown``) the LLM can reason
over and surface to the user with the cited NBC/IBC source section.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import (
    check_corridor_width,
    check_door_width,
    check_room_area,
)


# ─────────────────────────────────────────────────────────────────────
# Shared check-result envelope
# ─────────────────────────────────────────────────────────────────────


class CheckResult(BaseModel):
    """Outcome envelope for any clearance / area validator.

    Always non-error — bad input produces ``status='unknown'`` rather
    than raising.
    """

    status: str = Field(description="ok | warn_low | warn_high | unknown")
    message: str
    reference: Optional[str] = None
    """Human-readable reference (the row's display_name or notes)."""
    source_section: Optional[str] = None
    """NBC / IBC clause cited, e.g. 'NBC 2016 Part 4 §3.2.1'."""
    jurisdiction_used: Optional[str] = None
    """Which jurisdiction the check resolved against
    (``india_nbc`` baseline or a specific override)."""


# ─────────────────────────────────────────────────────────────────────
# check_door_width
# ─────────────────────────────────────────────────────────────────────


class CheckDoorWidthInput(BaseModel):
    door_type: str = Field(
        description=(
            "Door category — one of: main_entry | interior | bathroom | "
            "emergency_egress | sliding."
        ),
        max_length=40,
    )
    width_mm: float = Field(
        ge=0,
        le=5000,
        description="Proposed door width in millimetres.",
    )
    jurisdiction: str = Field(
        default="india_nbc",
        description=(
            "Code jurisdiction. ``india_nbc`` (BRD baseline) or "
            "``international_ibc``. State / city overrides like "
            "``maharashtra_dcr`` fall back to baseline if unspecified."
        ),
    )


@tool(
    name="check_door_width",
    description=(
        "Validate a door width against NBC / BRD clearance rules. "
        "Returns ok / warn_low / warn_high with the source clause "
        "cited. Always call this before quoting door dimensions to "
        "the user — never guess from memory."
    ),
    timeout_seconds=8.0,
)
async def check_door_width_tool(
    ctx: ToolContext,
    input: CheckDoorWidthInput,
) -> CheckResult:
    result = await check_door_width(
        ctx.session,
        door_type=input.door_type,
        width_mm=input.width_mm,
        jurisdiction=input.jurisdiction,
    )
    return CheckResult(
        status=result["status"],
        message=result["message"],
        reference=result.get("reference"),
        source_section=result.get("source_section"),
        jurisdiction_used=result.get("jurisdiction_used"),
    )


# ─────────────────────────────────────────────────────────────────────
# check_corridor_width
# ─────────────────────────────────────────────────────────────────────


class CheckCorridorWidthInput(BaseModel):
    segment: str = Field(
        description=(
            "Corridor segment type — residential | commercial | hospital | "
            "accessibility_universal."
        ),
        max_length=40,
    )
    width_mm: float = Field(
        ge=0,
        le=10000,
        description="Proposed corridor width in millimetres.",
    )
    jurisdiction: str = Field(default="india_nbc")


@tool(
    name="check_corridor_width",
    description=(
        "Validate a corridor minimum width against NBC / BRD circulation "
        "rules. Returns status + source clause. Use whenever a layout "
        "discussion involves corridors / passageways."
    ),
    timeout_seconds=8.0,
)
async def check_corridor_width_tool(
    ctx: ToolContext,
    input: CheckCorridorWidthInput,
) -> CheckResult:
    result = await check_corridor_width(
        ctx.session,
        segment=input.segment,
        width_mm=input.width_mm,
        jurisdiction=input.jurisdiction,
    )
    return CheckResult(
        status=result["status"],
        message=result["message"],
        reference=result.get("reference"),
        source_section=result.get("source_section"),
        jurisdiction_used=result.get("jurisdiction_used"),
    )


# ─────────────────────────────────────────────────────────────────────
# check_room_area
# ─────────────────────────────────────────────────────────────────────


class CheckRoomAreaInput(BaseModel):
    room_type: str = Field(
        description=(
            "Room slug. Residential: bedroom | kitchen | bathroom | "
            "living_room | dining_room | study | utility. Commercial: "
            "office_workstation | meeting_room | conference_room | "
            "reception | retail_floor. Hospitality: hotel_room_standard "
            "| hotel_suite | restaurant_seating | restaurant_kitchen | bar."
        ),
        max_length=64,
    )
    area_m2: float = Field(
        ge=0,
        le=10000,
        description="Proposed room area in square metres.",
    )
    segment: str = Field(
        default="residential",
        description="``residential`` | ``commercial`` | ``hospitality``.",
    )
    jurisdiction: str = Field(default="india_nbc")


@tool(
    name="check_room_area",
    description=(
        "Validate a room area against BRD / NBC space-planning standards. "
        "Returns status + cited source. Always run this before quoting "
        "room sizes — covers residential, commercial, hospitality."
    ),
    timeout_seconds=8.0,
)
async def check_room_area_tool(
    ctx: ToolContext,
    input: CheckRoomAreaInput,
) -> CheckResult:
    result = await check_room_area(
        ctx.session,
        room_type=input.room_type,
        area_m2=input.area_m2,
        segment=input.segment,
        jurisdiction=input.jurisdiction,
    )
    return CheckResult(
        status=result["status"],
        message=result["message"],
        reference=result.get("reference"),
        source_section=result.get("source_section"),
        jurisdiction_used=result.get("jurisdiction_used"),
    )
