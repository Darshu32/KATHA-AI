"""Ergonomics validation tools (Stage 4A).

Wraps Stage 3E ``ergonomics_lookup`` helpers — furniture dimension
range checks for chairs, tables, beds, storage.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import ergonomics_lookup as el


# ─────────────────────────────────────────────────────────────────────
# check_ergonomic_range
# ─────────────────────────────────────────────────────────────────────


class CheckErgonomicRangeInput(BaseModel):
    item_group: str = Field(
        description=(
            "Furniture group. One of: chair | table | bed | storage."
        ),
        max_length=20,
    )
    item: str = Field(
        description=(
            "Specific item slug. Chairs: dining_chair | armchair | "
            "lounge_chair | office_chair. Tables: dining_table | "
            "coffee_table | desk | console_table | side_table. Beds: "
            "single | double | queen | king. Storage: bookshelf | "
            "object_shelf | display_shelf | cabinet | wardrobe | "
            "kitchen_cabinet_base | kitchen_cabinet_wall | counter | "
            "tv_unit."
        ),
        max_length=64,
    )
    dim: str = Field(
        description=(
            "Dimension key — accepts both bare ('seat_height') and "
            "fully-qualified ('seat_height_mm') forms. Common dims: "
            "seat_height, seat_depth, seat_width, backrest_height, "
            "arm_height, overall_width, overall_depth, height, "
            "depth, length, width, shelf_depth, shelf_pitch, "
            "platform_height, raised_height, mattress, hang_rail_height, "
            "toe_kick_height."
        ),
        max_length=64,
    )
    value_mm: float = Field(ge=0, le=10000)
    jurisdiction: str = Field(default="india_nbc")


class CheckErgonomicRangeOutput(BaseModel):
    status: str = Field(
        description="ok | warn_low | warn_high | unknown"
    )
    message: str


@tool(
    name="check_ergonomic_range",
    description=(
        "Validate a furniture dimension (seat height, table depth, "
        "shelf pitch, etc.) against BRD §1C ergonomic ranges. Returns "
        "ok / warn_low / warn_high. Always run before quoting a "
        "specific dimension to a fabricator or client — chair seat "
        "heights, desk depths, bed platforms all have BRD bands the "
        "agent must respect."
    ),
    timeout_seconds=8.0,
)
async def check_ergonomic_range(
    ctx: ToolContext,
    input: CheckErgonomicRangeInput,
) -> CheckErgonomicRangeOutput:
    result = await el.check_range(
        ctx.session,
        category=input.item_group,
        item=input.item,
        dim=input.dim,
        value_mm=input.value_mm,
        jurisdiction=input.jurisdiction,
    )
    return CheckErgonomicRangeOutput(
        status=result["status"],
        message=result["message"],
    )


# ─────────────────────────────────────────────────────────────────────
# lookup_ergonomic_envelope
# ─────────────────────────────────────────────────────────────────────


class LookupErgonomicEnvelopeInput(BaseModel):
    item_group: str = Field(
        description="chair | table | bed | storage", max_length=20
    )
    item: str = Field(max_length=64)
    jurisdiction: str = Field(default="india_nbc")


class LookupErgonomicEnvelopeOutput(BaseModel):
    found: bool
    item_group: str
    item: str
    envelope: Optional[dict[str, Any]] = None
    """Full BRD ergonomic envelope. Each dim is a [low_mm, high_mm] band."""


@tool(
    name="lookup_ergonomic_envelope",
    description=(
        "Fetch the full BRD ergonomic envelope for a furniture item — "
        "every relevant dimension as a [low, high] mm range. Use when "
        "designing a piece from scratch (read all dims at once) rather "
        "than validating a single dim."
    ),
    timeout_seconds=8.0,
)
async def lookup_ergonomic_envelope(
    ctx: ToolContext,
    input: LookupErgonomicEnvelopeInput,
) -> LookupErgonomicEnvelopeOutput:
    spec = await el.get_ergonomics(
        ctx.session,
        item_group=input.item_group,
        item=input.item,
        jurisdiction=input.jurisdiction,
    )
    return LookupErgonomicEnvelopeOutput(
        found=spec is not None,
        item_group=input.item_group,
        item=input.item,
        envelope=spec,
    )
