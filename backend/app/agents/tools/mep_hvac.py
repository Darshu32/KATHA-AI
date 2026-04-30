"""HVAC sizing tools (Stage 4B).

Wraps Stage 3C ``mep_sizing`` helpers. The composite ``size_hvac_room``
tool answers the actual architect question — *"what AC do I need for
this bedroom?"* — by chaining ACH → CFM → tonnage → equipment
shortlist in one call. The primitive ``size_duct`` is for fine-grained
duct sizing follow-ups.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.standards import mep_sizing


# ─────────────────────────────────────────────────────────────────────
# size_hvac_room — composite (ACH + CFM + tonnage + equipment)
# ─────────────────────────────────────────────────────────────────────


class SizeHVACRoomInput(BaseModel):
    use_type: str = Field(
        description=(
            "Room use type. One of: bedroom | living_room | kitchen | "
            "bathroom | office_general | conference_room | "
            "restaurant_dining | restaurant_kitchen | retail | hotel_room "
            "| gym | classroom."
        ),
        max_length=64,
    )
    room_volume_m3: float = Field(
        ge=0,
        le=100000,
        description=(
            "Room volume (length × width × height) in m³. Drives air-changes "
            "calculation."
        ),
    )
    floor_area_m2: float = Field(
        ge=0,
        le=10000,
        description=(
            "Floor area in m². Drives cooling load (tonnage) calculation. "
            "Pass 0 if you only need ventilation CFM, no AC sizing."
        ),
    )
    cooling_use_type: Optional[str] = Field(
        default=None,
        description=(
            "Use type for cooling-load lookup if it differs from "
            "ventilation use type. e.g. 'office_general'. If null, "
            "falls back to ``use_type``."
        ),
        max_length=64,
    )
    jurisdiction: str = Field(default="india_nbc")


class HVACEquipmentRecommendation(BaseModel):
    required_tr: float
    selected_tr: float
    type: str
    note: Optional[str] = None


class HVACBTUOutput(BaseModel):
    btu_per_hr: float
    kw_thermal: float


class SizeHVACRoomOutput(BaseModel):
    use_type: str
    air_changes_per_hour: Optional[float] = None
    cfm_total: Optional[float] = None
    tonnage: Optional[float] = None
    equipment: Optional[HVACEquipmentRecommendation] = None
    capacity: Optional[HVACBTUOutput] = None
    notes: list[str]


@tool(
    name="size_hvac_room",
    description=(
        "One-shot HVAC sizing for a single room. Computes air-changes-per-hour, "
        "ventilation CFM (m³ × ACH / 60), cooling tonnage (TR per m² × area), "
        "and a standard-size equipment shortlist (e.g. '1.5 TR wall split'). "
        "Use this whenever the user asks 'what AC do I need' or 'how much "
        "ventilation' — preferred over chaining the primitives manually."
    ),
    timeout_seconds=10.0,
)
async def size_hvac_room(
    ctx: ToolContext,
    input: SizeHVACRoomInput,
) -> SizeHVACRoomOutput:
    notes: list[str] = []

    # Ventilation CFM via ACH.
    cfm_result = await mep_sizing.hvac_cfm(
        ctx.session,
        room_volume_m3=input.room_volume_m3,
        use_type=input.use_type,
        jurisdiction=input.jurisdiction,
    )
    if "error" in cfm_result:
        notes.append(f"CFM lookup: {cfm_result['error']}")
        ach = None
        cfm_total = None
    else:
        ach = float(cfm_result["ach"])
        cfm_total = float(cfm_result["cfm_total"])

    # Cooling load → tonnage. Skipped when floor_area_m2 == 0.
    tonnage: Optional[float] = None
    equipment: Optional[HVACEquipmentRecommendation] = None
    capacity: Optional[HVACBTUOutput] = None

    if input.floor_area_m2 > 0:
        cooling_use = input.cooling_use_type or input.use_type
        cooling_result = await mep_sizing.cooling_tr(
            ctx.session,
            area_m2=input.floor_area_m2,
            use_type=cooling_use,
            jurisdiction=input.jurisdiction,
        )
        if "error" in cooling_result:
            notes.append(
                f"Cooling-load lookup for {cooling_use!r}: {cooling_result['error']}. "
                "Tonnage skipped."
            )
        else:
            tonnage = float(cooling_result["tonnage"])
            equip = await mep_sizing.equipment_shortlist(
                ctx.session,
                tonnage_required=tonnage,
                jurisdiction=input.jurisdiction,
            )
            if "error" in equip:
                notes.append(f"Equipment shortlist: {equip['error']}")
            else:
                equipment = HVACEquipmentRecommendation(
                    required_tr=float(equip["required_tr"]),
                    selected_tr=float(equip["selected_tr"]),
                    type=str(equip["type"]),
                    note=equip.get("note"),
                )
                cap = mep_sizing.equipment_capacity(equipment.selected_tr)
                capacity = HVACBTUOutput(
                    btu_per_hr=float(cap["btu_per_hr"]),
                    kw_thermal=float(cap["kw_thermal"]),
                )

    return SizeHVACRoomOutput(
        use_type=input.use_type,
        air_changes_per_hour=ach,
        cfm_total=cfm_total,
        tonnage=tonnage,
        equipment=equipment,
        capacity=capacity,
        notes=notes,
    )


# ─────────────────────────────────────────────────────────────────────
# size_duct — primitive (CFM → round diameter)
# ─────────────────────────────────────────────────────────────────────


class SizeDuctInput(BaseModel):
    cfm: float = Field(
        ge=0,
        le=100000,
        description="Airflow in CFM. Drives the duct-sizing chart lookup.",
    )
    jurisdiction: str = Field(default="india_nbc")


class SizeDuctOutput(BaseModel):
    cfm: float
    diameter_mm: int
    note: Optional[str] = None


@tool(
    name="size_duct",
    description=(
        "Pick a standard round-duct diameter for a given CFM (≈4 m/s "
        "branch velocity). Use after ``size_hvac_room`` if the user "
        "drills into duct routing. Returns the smallest standard "
        "diameter that handles the airflow."
    ),
    timeout_seconds=8.0,
)
async def size_duct(
    ctx: ToolContext,
    input: SizeDuctInput,
) -> SizeDuctOutput:
    result = await mep_sizing.duct_round_diameter(
        ctx.session, cfm=input.cfm, jurisdiction=input.jurisdiction
    )
    if "error" in result:
        return SizeDuctOutput(
            cfm=input.cfm, diameter_mm=0, note=str(result["error"])
        )
    return SizeDuctOutput(
        cfm=float(result["cfm"]),
        diameter_mm=int(result["diameter_mm"]),
        note=result.get("note"),
    )
