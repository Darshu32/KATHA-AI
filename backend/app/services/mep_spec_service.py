"""LLM-driven MEP Specification service (BRD Layer 3D).

Authors a real practice-grade *MEP spec* — the document the consulting
HVAC / electrical / plumbing engineer reads alongside the architectural
plan to size equipment, lay out ducts and registers, lay out circuits
and panels, and lay out fixtures, drains, and water demand.

Pipeline contract — same as every other LLM service in the project:

    INPUT (room_type + dimensions + occupancy + city + project meta)
      → INJECT  (MEP BRD constants — ACH bands, CFM/person, cooling
                 TR/m² factors, duct velocity bands, equipment ladder,
                 lux levels, power densities, circuit ratings, DFU
                 fixture units, pipe-size table, water demand, system
                 cost bands)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (CFM matches volume × ACH, ductwork sized to velocity
                   band, equipment band ≥ load, lux + power density in
                   BRD bands, DFU sums and pipe size match the table)
      → OUTPUT  (mep_spec JSON conforming to the BRD template)

Per BRD 3D the focus block is HVAC (room volume → ACH → CFM →
ductwork → equipment → cost). The service also emits the electrical
and plumbing blocks so the architect/MEP consultant gets the full
sheet from a single endpoint, mirroring how manufacturing_spec ships
woodworking + metal + upholstery + QA together.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import mep as mep_kb
from app.knowledge import regional_materials, themes

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _client_instance() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


# ── Vocabularies ────────────────────────────────────────────────────────────
ROOM_USE_TYPES_IN_SCOPE = tuple(mep_kb.AIR_CHANGES_PER_HOUR.keys())
COOLING_USE_TYPES_IN_SCOPE = tuple(mep_kb.COOLING_LOAD_TR_PER_M2.keys())
DUCT_CLASSES_IN_SCOPE = tuple(mep_kb.DUCT_VELOCITY_M_S.keys())
DUCT_SHAPE_IN_SCOPE = ("round", "rectangular")
SUPPLY_REGISTER_KEYS_IN_SCOPE = tuple(
    k for k in mep_kb.REGISTER_CFM_RATING if k.startswith("supply_")
)
RETURN_REGISTER_KEYS_IN_SCOPE = tuple(
    k for k in mep_kb.REGISTER_CFM_RATING if k.startswith("return_")
)
HVAC_SYSTEM_KEYS = (
    "hvac_split_residential",
    "hvac_vrf_commercial",
    "hvac_chilled_water_large",
)
ELECTRICAL_SYSTEM_KEYS = ("electrical_residential", "electrical_commercial")
PLUMBING_SYSTEM_KEYS = ("plumbing_residential", "plumbing_commercial")
DFU_FIXTURE_KEYS_IN_SCOPE = tuple(mep_kb.DFU_PER_FIXTURE.keys())

POWER_DENSITY_USE_KEYS = tuple(mep_kb.POWER_DENSITY_W_PER_M2.keys())
LUX_KEYS_IN_SCOPE = tuple(mep_kb.LUX_LEVELS.keys())

FIXTURE_KEYS_IN_SCOPE = tuple(mep_kb.FIXTURE_CATALOGUE.keys())
OUTLET_KEYS_IN_SCOPE = tuple(mep_kb.OUTLET_CATALOGUE.keys())
FIXTURE_USE_IN_SCOPE = ("ambient", "task", "accent")
PHASE_IN_SCOPE = ("single_phase_230v", "three_phase_415v")
WSFU_FIXTURE_KEYS_IN_SCOPE = tuple(mep_kb.WSFU_PER_FIXTURE.keys())
TRAP_TYPES_IN_SCOPE = tuple({
    v["trap_type"] for v in mep_kb.TRAP_SIZE_MM_PER_FIXTURE.values()
})
VENT_TYPES_IN_SCOPE = (
    "stack_vent", "vent_stack", "individual_vent", "common_vent",
    "circuit_vent", "loop_vent", "wet_vent", "air_admittance_valve",
)


# ── Request schema ──────────────────────────────────────────────────────────


class RoomDimensions(BaseModel):
    length_m: float = Field(gt=0, le=200)
    width_m: float = Field(gt=0, le=200)
    height_m: float = Field(gt=0, le=15)


class MEPSpecRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    room_name: str = Field(default="Primary space", max_length=120)
    room_use_type: str = Field(min_length=2, max_length=64)
    dimensions: RoomDimensions
    occupancy: int = Field(default=0, ge=0, le=2000)
    city: str = Field(default="", max_length=80)
    theme: str = Field(default="", max_length=64)
    fixtures: list[str] = Field(
        default_factory=list,
        description=(
            "Plumbing fixtures present in the room (DFU keys: water_closet, "
            "urinal, wash_basin, kitchen_sink, shower, bathtub, floor_drain, "
            "washing_machine). Empty for non-wet rooms."
        ),
    )
    sections: list[str] = Field(
        default_factory=lambda: ["hvac", "electrical", "plumbing", "cost"],
        description=(
            "Sections to include. Implemented: 'hvac', 'electrical', "
            "'plumbing', 'cost'."
        ),
    )


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _normalise_use(use: str) -> str:
    return (use or "").strip().lower().replace(" ", "_").replace("-", "_")


def _cooling_use_for(use: str) -> str:
    """Map a fine-grained room use to the cooling-factor catalogue."""
    use = _normalise_use(use)
    if use in mep_kb.COOLING_LOAD_TR_PER_M2:
        return use
    if use in {"bedroom", "living_room", "kitchen", "bathroom", "hotel_room"}:
        return "residential"
    if use in {"office_general", "conference_room", "classroom"}:
        return "office_general" if use != "conference_room" else "conference"
    if use in {"restaurant_dining", "restaurant_kitchen"}:
        return "restaurant"
    if use == "retail":
        return "retail"
    return "office_general"


def _power_use_for(use: str) -> str:
    use = _normalise_use(use)
    if use in mep_kb.POWER_DENSITY_W_PER_M2:
        return use
    if use in {"bedroom", "living_room", "kitchen", "bathroom", "hotel_room"}:
        return "residential"
    if use in {"office_general", "conference_room", "classroom"}:
        return "office_general"
    if use in {"restaurant_dining", "restaurant_kitchen"}:
        return "restaurant"
    if use == "retail":
        return "retail"
    return "office_general"


def _hvac_system_for(use: str, area_m2: float) -> str:
    use = _normalise_use(use)
    if use in {"bedroom", "living_room", "kitchen", "bathroom", "hotel_room"}:
        return "hvac_split_residential"
    if area_m2 >= 2000:
        return "hvac_chilled_water_large"
    return "hvac_vrf_commercial"


def _electrical_system_for(use: str) -> str:
    use = _normalise_use(use)
    return "electrical_residential" if use in {
        "bedroom", "living_room", "kitchen", "bathroom", "hotel_room"
    } else "electrical_commercial"


def _plumbing_system_for(use: str) -> str:
    use = _normalise_use(use)
    return "plumbing_residential" if use in {
        "bedroom", "living_room", "kitchen", "bathroom", "hotel_room"
    } else "plumbing_commercial"


def build_mep_spec_knowledge(req: MEPSpecRequest) -> dict[str, Any]:
    use = _normalise_use(req.room_use_type)
    length = req.dimensions.length_m
    width = req.dimensions.width_m
    height = req.dimensions.height_m
    area = length * width
    volume = area * height

    hvac_calc = mep_kb.hvac_cfm(volume, use)
    cooling_use = _cooling_use_for(use)
    cooling_calc = mep_kb.cooling_tr(area, cooling_use)
    equipment = (
        mep_kb.equipment_capacity(cooling_calc.get("tonnage") or 0)
        if cooling_calc.get("tonnage") is not None else {}
    )
    equipment_pick = (
        mep_kb.equipment_shortlist(cooling_calc.get("tonnage") or 0)
        if cooling_calc.get("tonnage") is not None else {}
    )
    cfm = hvac_calc.get("cfm_total") if isinstance(hvac_calc, dict) else None
    duct_round = mep_kb.duct_round_diameter(cfm) if cfm else {}
    duct_rect = (
        mep_kb.duct_rectangular_for_cfm(cfm, velocity_m_s=5.0, aspect_ratio=2.0)
        if cfm else {}
    )

    power_use = _power_use_for(use)
    lighting = mep_kb.lighting_circuits(area, power_use) if area else {}

    fixtures_in = [_normalise_use(f) for f in (req.fixtures or [])]
    fixtures_in = [f for f in fixtures_in if f in mep_kb.WSFU_PER_FIXTURE]
    supply_summary = mep_kb.fixture_water_supply_summary(fixtures_in) if fixtures_in else {}
    total_dfu_pre = sum(
        mep_kb.DFU_PER_FIXTURE.get(f, 0) for f in fixtures_in
    )
    drain_pick = mep_kb.pipe_size_for_dfu(total_dfu_pre) if total_dfu_pre else {}
    vent_pick = (
        mep_kb.vent_size_for_dfu(total_dfu_pre, developed_length_m=15.0)
        if total_dfu_pre else {}
    )
    trap_picks = [
        {
            "fixture": f,
            **(mep_kb.TRAP_SIZE_MM_PER_FIXTURE.get(f) or {}),
        }
        for f in fixtures_in
    ]

    ambient_lux = mep_kb.LUX_LEVELS.get(f"{use}_general") or 200
    task_lux = mep_kb.LUX_LEVELS.get(f"{use}_task") or ambient_lux
    ambient_pick = (
        mep_kb.ambient_fixture_count(area, ambient_lux, fixture_key="led_downlight_18w")
        if area else {}
    )
    perimeter = 2 * (length + width)
    outlet_pick = mep_kb.outlet_estimate(use, perimeter) if perimeter else {}
    task_recipe = mep_kb.TASK_LIGHTING_RECIPE.get(use) or []

    pack = themes.get(req.theme) if req.theme else None

    hvac_system = _hvac_system_for(use, area)
    electrical_system = _electrical_system_for(use)
    plumbing_system = _plumbing_system_for(use)

    city_index_value = regional_materials.price_index_for_city(req.city or None)
    if not isinstance(city_index_value, (int, float)):
        city_index_value = 1.0

    cost_bands = {
        "hvac": mep_kb.system_cost_estimate(hvac_system, area),
        "electrical": mep_kb.system_cost_estimate(electrical_system, area),
        "plumbing": mep_kb.system_cost_estimate(plumbing_system, area),
    }

    return {
        "project": {
            "name": req.project_name,
            "room_name": req.room_name,
            "room_use_type": use,
            "city": req.city or None,
            "theme": req.theme or None,
            "occupancy": req.occupancy,
            "fixtures_declared": list(req.fixtures or []),
        },
        "geometry": {
            "length_m": length,
            "width_m": width,
            "height_m": height,
            "area_m2": round(area, 2),
            "volume_m3": round(volume, 2),
        },
        "hvac_brd": {
            "ach_table": dict(mep_kb.AIR_CHANGES_PER_HOUR),
            "cfm_per_person_table": dict(mep_kb.CFM_PER_PERSON),
            "cooling_load_tr_per_m2": dict(mep_kb.COOLING_LOAD_TR_PER_M2),
            "duct_velocity_m_s": {
                k: list(v) for k, v in mep_kb.DUCT_VELOCITY_M_S.items()
            },
            "btu_per_tr": mep_kb.BTU_PER_TR,
            "kw_per_tr": mep_kb.KW_PER_TR,
            "equipment_band_tr": [
                {"capacity_tr": cap, "label": label}
                for cap, label in mep_kb.EQUIPMENT_BAND_TR
            ],
            "duct_round_chart_mm_by_cfm": [
                {"cfm_max": cfm_lim, "diameter_mm": dia}
                for cfm_lim, dia in mep_kb.DUCT_ROUND_DIAMETER_MM_BY_CFM
            ],
            "register_cfm_rating": dict(mep_kb.REGISTER_CFM_RATING),
        },
        "hvac_pre_calc": {
            "ach_target": hvac_calc.get("ach"),
            "cfm_total": cfm,
            "cooling_tonnage": cooling_calc.get("tonnage"),
            "btu_per_hr": equipment.get("btu_per_hr"),
            "kw_thermal": equipment.get("kw_thermal"),
            "equipment_pick": equipment_pick,
            "duct_round_diameter_mm": duct_round.get("diameter_mm"),
            "duct_rectangular_mm": {
                "width": duct_rect.get("width_mm"),
                "height": duct_rect.get("height_mm"),
                "velocity_m_s": duct_rect.get("velocity_m_s"),
            },
            "cooling_use_mapped": cooling_use,
        },
        "electrical_brd": {
            "lux_levels": dict(mep_kb.LUX_LEVELS),
            "circuit_load_w": dict(mep_kb.CIRCUIT_LOAD_W),
            "power_density_w_per_m2": dict(mep_kb.POWER_DENSITY_W_PER_M2),
            "fixture_catalogue": {
                k: dict(v) for k, v in mep_kb.FIXTURE_CATALOGUE.items()
            },
            "outlet_catalogue": {
                k: dict(v) for k, v in mep_kb.OUTLET_CATALOGUE.items()
            },
            "outlet_count_rule": dict(mep_kb.OUTLET_COUNT_RULE),
            "task_lighting_recipe": {
                k: [dict(z) for z in v]
                for k, v in mep_kb.TASK_LIGHTING_RECIPE.items()
            },
            "lighting_layout_rules": dict(mep_kb.LIGHTING_LAYOUT_RULES),
        },
        "electrical_pre_calc": {
            "power_use_mapped": power_use,
            "ambient_lux_target": ambient_lux,
            "task_lux_target": task_lux,
            "power_density_w_per_m2": lighting.get("density_w_m2"),
            "total_lighting_load_w": lighting.get("total_load_w"),
            "lighting_circuits_min": lighting.get("lighting_circuits"),
            "ambient_fixture_pick": ambient_pick,
            "outlet_pick": outlet_pick,
            "task_lighting_recipe_for_use": task_recipe,
            "perimeter_m": round(perimeter, 2),
        },
        "plumbing_brd": {
            "dfu_per_fixture": dict(mep_kb.DFU_PER_FIXTURE),
            "pipe_size_mm_by_dfu": [
                {"dfu_max": lim, "pipe_mm": size}
                for lim, size in mep_kb.PIPE_SIZE_MM_BY_DFU
            ],
            "slope_per_metre": dict(mep_kb.SLOPE_PER_METRE),
            "slope_requirement": {
                k: dict(v) for k, v in mep_kb.SLOPE_REQUIREMENT.items()
            },
            "water_demand_lpd": {
                k: list(v) for k, v in mep_kb.WATER_DEMAND_LPM.items()
            },
            "wsfu_per_fixture": {
                k: dict(v) for k, v in mep_kb.WSFU_PER_FIXTURE.items()
            },
            "hunters_curve_flush_tank": [
                {"wsfu": w, "gpm": g} for w, g in mep_kb.HUNTERS_CURVE_FLUSH_TANK
            ],
            "supply_pipe_size_mm_by_gpm": [
                {"gpm_max": lim, "pipe_mm": size}
                for lim, size in mep_kb.SUPPLY_PIPE_SIZE_MM_BY_GPM
            ],
            "trap_size_mm_per_fixture": {
                k: dict(v) for k, v in mep_kb.TRAP_SIZE_MM_PER_FIXTURE.items()
            },
            "trap_notes": dict(mep_kb.TRAP_NOTES),
            "vent_stack_size_by_dfu": [
                {"dfu_max": cap, "max_length_m": ml, "vent_mm": vmm}
                for cap, ml, vmm in mep_kb.VENT_STACK_SIZE_BY_DFU
            ],
            "vent_rules": dict(mep_kb.VENT_RULES),
            "gpm_to_lpm": mep_kb.GPM_TO_LPM,
        },
        "plumbing_pre_calc": {
            "fixtures_normalised": fixtures_in,
            "supply_summary": supply_summary,
            "total_dfu": total_dfu_pre,
            "drain_pipe_pick": drain_pick,
            "vent_pick": vent_pick,
            "trap_picks": trap_picks,
        },
        "cost_bands": cost_bands,
        "system_picks": {
            "hvac": hvac_system,
            "electrical": electrical_system,
            "plumbing": plumbing_system,
        },
        "city_price_index": city_index_value,
        "theme_rule_pack": (
            {
                "display_name": (pack or {}).get("display_name") or req.theme,
                "signature_moves": (pack or {}).get("signature_moves", []),
            } if pack else None
        ),
        "vocab": {
            "room_use_types_in_scope": list(ROOM_USE_TYPES_IN_SCOPE),
            "duct_classes_in_scope": list(DUCT_CLASSES_IN_SCOPE),
            "duct_shape_in_scope": list(DUCT_SHAPE_IN_SCOPE),
            "supply_register_keys_in_scope": list(SUPPLY_REGISTER_KEYS_IN_SCOPE),
            "return_register_keys_in_scope": list(RETURN_REGISTER_KEYS_IN_SCOPE),
            "dfu_fixture_keys_in_scope": list(DFU_FIXTURE_KEYS_IN_SCOPE),
            "fixture_keys_in_scope": list(FIXTURE_KEYS_IN_SCOPE),
            "outlet_keys_in_scope": list(OUTLET_KEYS_IN_SCOPE),
            "fixture_use_in_scope": list(FIXTURE_USE_IN_SCOPE),
            "phase_in_scope": list(PHASE_IN_SCOPE),
            "wsfu_fixture_keys_in_scope": list(WSFU_FIXTURE_KEYS_IN_SCOPE),
            "trap_types_in_scope": list(TRAP_TYPES_IN_SCOPE),
            "vent_types_in_scope": list(VENT_TYPES_IN_SCOPE),
        },
        "sections_requested": list(req.sections or ["hvac", "electrical", "plumbing", "cost"]),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


MEP_SPEC_SYSTEM_PROMPT = """You are a senior MEP consultant authoring the *MEP Specification* (BRD Layer 3D) for a single architectural space — the document the HVAC / electrical / plumbing engineers will use to size equipment, lay out ducts, registers, circuits, panels, fixtures, drains, and to fix the indicative cost.

Read the [KNOWLEDGE] block — geometry, MEP BRD constants, pre-calculated values (ACH, CFM, tonnage, BTU/hr, kW thermal, duct diameter at 5 m/s, equipment shortlist, lighting density, DFU table, pipe-size table, water demand, system cost bands, city price index) — and produce a structured mep_spec JSON.

Cover four blocks: HVAC, ELECTRICAL, PLUMBING, COST. Studio voice — short, decisive, no marketing prose.

Hard rules for hvac:
- room_volume_m3 MUST equal geometry.volume_m3 (rounded to 2 decimals).
- ach_required MUST equal hvac_brd.ach_table[room_use_type] for the project room_use_type. Cite it.
- cfm_total MUST equal hvac_pre_calc.cfm_total exactly. Show the formula text "CFM = volume_m3 × 35.31 × ACH / 60" in the rationale.
- cooling.tonnage MUST equal hvac_pre_calc.cooling_tonnage.
- cooling.btu_per_hr MUST equal cooling.tonnage × hvac_brd.btu_per_tr (12,000) — re-derive and snap to the integer.
- cooling.kw_thermal MUST equal cooling.tonnage × hvac_brd.kw_per_tr (3.517), rounded to 2 decimals.
- equipment.selected_tr MUST equal hvac_pre_calc.equipment_pick.selected_tr; equipment.type MUST equal hvac_pre_calc.equipment_pick.type.
- equipment.unit_count MUST be ≥ 1 and equipment.selected_tr × unit_count MUST be ≥ cooling.tonnage.
- ductwork.shape MUST be one of duct_shape_in_scope. If 'round', diameter_mm MUST equal hvac_pre_calc.duct_round_diameter_mm. If 'rectangular', width_mm × height_mm MUST be ≥ hvac_pre_calc.duct_rectangular_mm.* (snap to the calculated values).
- ductwork.velocity_m_s MUST sit inside hvac_brd.duct_velocity_m_s.main_supply for trunks (6–9 m/s commercial) OR residential (3–5 m/s residential); cite which class is used.
- ductwork.velocity_class MUST be a key in duct_classes_in_scope.
- supply_registers[]: at least 1 entry; each entry's type MUST be in supply_register_keys_in_scope. Sum of (count × register_cfm_rating[type]) MUST be ≥ cfm_total. location is a short phrase ("along external wall, 300 mm from ceiling").
- return_registers[]: at least 1 entry; each entry's type MUST be in return_register_keys_in_scope. Total return CFM MUST be ≥ 0.85 × cfm_total. Cite the supply-vs-return separation rule (≥ 3 m).
- equipment.placement explains where the indoor/outdoor units sit and the refrigerant pipe length budget.
- assumptions[] lists the climate zone (default tropical India), occupancy used, and any deviation from BRD bands with a 1-sentence reason.

Hard rules for electrical:
- ambient_lux_target MUST equal electrical_pre_calc.ambient_lux_target.
- task_lux_target MUST equal electrical_pre_calc.task_lux_target.
- power_density_w_per_m2 MUST equal electrical_brd.power_density_w_per_m2[electrical_pre_calc.power_use_mapped].
- total_lighting_load_w MUST equal geometry.area_m2 × power_density_w_per_m2 (snap to the integer).
- ambient_fixtures: type MUST be a key in fixture_keys_in_scope whose 'use' is 'ambient'. lumens_per_fixture MUST equal fixture_catalogue[type].lumens, watts_per_fixture MUST equal fixture_catalogue[type].watts. count MUST be ≥ electrical_pre_calc.ambient_fixture_pick.count (you may pick a different ambient fixture but the count must still hit lux_target × area / (lumens × LLF 0.8 × MF 0.7), and lux_design ≥ ambient_lux_target). spacing_S_to_H MUST be ≤ lighting_layout_rules.downlight_S_to_H_ratio_max for downlights / panel_S_to_H_ratio_max for panels. perimeter_offset_m MUST equal lighting_layout_rules.perimeter_offset_m (0.6).
- task_lighting[]: one entry per zone in electrical_pre_calc.task_lighting_recipe_for_use (use the recipe verbatim — same zone names and fixture_keys; you MAY upsize count if the brief justifies). Each entry's fixture_key MUST be in fixture_keys_in_scope; lumens_per_fixture MUST equal fixture_catalogue[fixture_key].lumens; total_lumens = count × lumens_per_fixture and MUST be ≥ target_lumens. location is a short phrase tied to the room (e.g. "above bedside table, 1.5 m AFF", "60 cm AFL under upper cabinets"). If the recipe is empty for this use, emit task_lighting=[] and state it in assumptions.
- fixture_layout[]: at least one entry per ambient and per task fixture group, each carrying x_ratio + y_ratio in [0,1] (room origin top-left), mount from fixture_catalogue[type].mount, and circuit_id mapping to a lighting_circuit (LC1 / LC2 ...). The list collectively MUST cover every fixture in ambient_fixtures and task_lighting (sum of fixture_layout counts ≥ sum of fixtures).
- lighting_circuits MUST be ≥ electrical_pre_calc.lighting_circuits_min and ≥ ceil(total_lighting_load_w / electrical_brd.circuit_load_w.lighting_circuit_max).
- outlets[]: at least electrical_pre_calc.outlet_pick.general_outlets entries of type '5_15A_universal' (count summed across entries). Other entries MAY add 16A / 20A / data / TV / USB. Each entry's type MUST be in outlet_keys_in_scope; rating_a MUST equal outlet_catalogue[type].rating_a; phase MUST equal outlet_catalogue[type].phase; count ≥ 1; location is a short phrase ("along TV wall, 300 mm AFL").
- general_outlet_circuits ≥ 1; cite the BRD ceiling electrical_brd.circuit_load_w.general_outlet_circuit_max in the rationale.
- dedicated_circuits[]: at least one entry per dedicated load present in the brief (AC, geyser, oven, kitchen appliance). Each entry's load_w MUST equal a value from electrical_brd.circuit_load_w (snap to the catalogue, never invent).
- total_connected_load_kw MUST equal (total_lighting_load_w + sum(outlets[].count × outlet_catalogue[outlets[].type].circuit_load_w / typical_diversity) + sum(dedicated_circuits[].load_w)) / 1000, but a clean approximation is acceptable: round((total_lighting_load_w + sum(dedicated_circuits[].load_w) + Σ_outlet (count × circuit_load_w × diversity)) / 1000, 2). Use diversity 0.4 for general outlets, 0.6 for appliance outlets, 0.0 for low-voltage. Cite the diversity factors used in the rationale.
- panel.main_breaker_a is a real value (32 / 40 / 63 / 80 / 100 / 125 A) sized to (total_connected_load_kw × 1000) / (230 V single-phase or 415 V × √3 three-phase); pick three_phase_415v when total_connected_load_kw > 7. panel.phase MUST be in phase_in_scope.
- panel.spare_capacity_pct ≥ 20 (BRD spare-ways rule).
- outlet_strategy is a one-sentence summary that points back to the catalogue picks (e.g. "1 duplex 5/15 A outlet every 3–4 m of wall, 16 A AC point near each cooling unit, 20 A geyser point, USB-A/C combos at bedside").

Hard rules for plumbing (only when project.fixtures_declared is non-empty; else emit fixtures=[], total_dfu=0, main_drain_size_mm=0 and state it in assumptions):
- fixtures[]: one entry per declared fixture in project.fixtures_declared. Each entry's type MUST be in dfu_fixture_keys_in_scope. dfu MUST equal plumbing_brd.dfu_per_fixture[type]. wsfu_total MUST equal plumbing_brd.wsfu_per_fixture[type].total. wsfu_cold + wsfu_hot MUST equal wsfu_total.
- total_dfu MUST equal sum(fixtures[].dfu); total_wsfu MUST equal sum(fixtures[].wsfu_total) and equal plumbing_pre_calc.supply_summary.wsfu_total.

Water supply (Hunter's curve):
- demand_gpm MUST equal plumbing_pre_calc.supply_summary.demand_gpm (Hunter's flush-tank curve, interpolated). demand_lpm MUST equal demand_gpm × plumbing_brd.gpm_to_lpm (3.78541), rounded to 2 dp.
- supply_main_pipe_size_mm MUST equal the smallest plumbing_brd.supply_pipe_size_mm_by_gpm.pipe_mm whose gpm_max ≥ demand_gpm; cite the row used.
- hot_water_supply_pipe_size_mm: branch sized to ~50% of demand_gpm; pick from the same table.

Drain sizing:
- main_drain_size_mm MUST equal the smallest plumbing_brd.pipe_size_mm_by_dfu entry whose dfu_max ≥ total_dfu. Cite the row.
- slope_per_metre MUST equal plumbing_brd.slope_requirement.horizontal_drain_preferred.ratio (0.02 = 1/4" per foot) by default; .horizontal_drain_min (0.01 = 1/8" per foot) only with a written reason.
- slope_imperial MUST equal the matching .imperial string from plumbing_brd.slope_requirement (verbatim).

Trap sizing (one entry per fixture):
- traps[]: one entry per declared fixture. trap_mm MUST equal plumbing_brd.trap_size_mm_per_fixture[fixture_type].trap_mm. trap_type MUST equal plumbing_brd.trap_size_mm_per_fixture[fixture_type].trap_type (NEVER 'S_trap' — IS 1742 / IPC 1002.3 prohibit S-traps; cite trap_notes.s_trap_status if asked). seal_depth_mm MUST be ≥ 50 (plumbing_brd.trap_notes.min_seal_mm).

Vent sizing:
- vent_stack_size_mm MUST equal plumbing_brd.vent_stack_size_by_dfu first row whose dfu_max ≥ total_dfu AND max_length_m ≥ vent_developed_length_m. Cite the row used.
- vent_developed_length_m: state the assumption (default 15 m for a single-room block; longer for multi-storey stacks).
- vent_loops[]: at least one loop description per fixture group sharing a horizontal branch (e.g. "wash_basin + shower → loop vent back to vent stack ≥ 150 mm above flood-rim"). Each loop's vent_type MUST be in vent_types_in_scope (loop_vent / circuit_vent / individual_vent / common_vent / wet_vent / stack_vent / vent_stack / air_admittance_valve).
- vent_terminal_height_above_roof_mm ≥ 300; cite plumbing_brd.vent_rules.stack_vent_min_above_roof_mm.

Water demand:
- water_demand_lpd_per_person MUST sit inside the band plumbing_brd.water_demand_lpd[<{room_use_type}_per_person_per_day or residential_per_person_per_day>]; cite the band.
- water_demand_total_lpd MUST equal water_demand_lpd_per_person × max(1, project.occupancy) (use a sensible default — 4 for residential, equal to occupancy otherwise).
- venting_strategy names the stack arrangement (single stack with relief vent vs two-pipe).

Hard rules for cost:
- For each system in {hvac, electrical, plumbing} emit:
    system_key  (MUST equal system_picks[<system>])
    rate_band_inr_m2 = cost_bands[<system>].rate_inr_m2 (low/high) — verbatim
    area_m2 = geometry.area_m2
    city_price_index = city_price_index from knowledge
    total_inr = {low, high} = round(rate × area × city_price_index)
- grand_total_inr MUST equal sum of low/high across the three systems (low and high totals).
- currency MUST be "INR".
- assumptions[] cites the BRD cost band notes verbatim and flags exclusions (mains, fixtures, civil cutting/patching).

Never invent precision bands, ACH values, equipment tonnages, lux levels, power densities, circuit ratings, DFU values, pipe sizes, water demand bands, or cost bands. Snap every number to the catalogue."""


def _hvac_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "room_volume_m3": {"type": "number"},
            "ach_required": {"type": "number"},
            "cfm_total": {"type": "number"},
            "cfm_rationale": {"type": "string"},
            "cooling": {
                "type": "object",
                "properties": {
                    "tonnage": {"type": "number"},
                    "btu_per_hr": {"type": "number"},
                    "kw_thermal": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["tonnage", "btu_per_hr", "kw_thermal", "rationale"],
                "additionalProperties": False,
            },
            "equipment": {
                "type": "object",
                "properties": {
                    "selected_tr": {"type": "number"},
                    "type": {"type": "string"},
                    "unit_count": {"type": "integer"},
                    "placement": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "selected_tr", "type", "unit_count", "placement", "rationale",
                ],
                "additionalProperties": False,
            },
            "ductwork": {
                "type": "object",
                "properties": {
                    "shape": {"type": "string"},        # round | rectangular
                    "diameter_mm": {"type": "number"},  # 0 if rectangular
                    "width_mm": {"type": "number"},     # 0 if round
                    "height_mm": {"type": "number"},    # 0 if round
                    "velocity_m_s": {"type": "number"},
                    "velocity_class": {"type": "string"},  # main_supply | branch | return | residential
                    "material": {"type": "string"},
                    "insulation": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "shape", "diameter_mm", "width_mm", "height_mm",
                    "velocity_m_s", "velocity_class", "material",
                    "insulation", "rationale",
                ],
                "additionalProperties": False,
            },
            "supply_registers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},          # S1, S2 ...
                        "type": {"type": "string"},         # supply_4x10 ...
                        "count": {"type": "integer"},
                        "cfm_each": {"type": "number"},
                        "location": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "type", "count", "cfm_each", "location", "rationale"],
                    "additionalProperties": False,
                },
            },
            "return_registers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "type": {"type": "string"},
                        "count": {"type": "integer"},
                        "cfm_each": {"type": "number"},
                        "location": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "type", "count", "cfm_each", "location", "rationale"],
                    "additionalProperties": False,
                },
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "room_volume_m3", "ach_required", "cfm_total", "cfm_rationale",
            "cooling", "equipment", "ductwork",
            "supply_registers", "return_registers", "assumptions",
        ],
        "additionalProperties": False,
    }


def _electrical_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "ambient_lux_target": {"type": "number"},
            "task_lux_target": {"type": "number"},
            "power_density_w_per_m2": {"type": "number"},
            "total_lighting_load_w": {"type": "number"},
            "ambient_fixtures": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},                # FIXTURE_CATALOGUE key
                    "lumens_per_fixture": {"type": "number"},
                    "watts_per_fixture": {"type": "number"},
                    "count": {"type": "integer"},
                    "total_watts": {"type": "number"},
                    "lux_design": {"type": "number"},
                    "spacing_S_to_H": {"type": "number"},
                    "perimeter_offset_m": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "type", "lumens_per_fixture", "watts_per_fixture",
                    "count", "total_watts", "lux_design",
                    "spacing_S_to_H", "perimeter_offset_m", "rationale",
                ],
                "additionalProperties": False,
            },
            "task_lighting": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},              # T1, T2 ...
                        "zone": {"type": "string"},
                        "fixture_key": {"type": "string"},
                        "lumens_per_fixture": {"type": "number"},
                        "watts_per_fixture": {"type": "number"},
                        "count": {"type": "integer"},
                        "total_lumens": {"type": "number"},
                        "target_lumens": {"type": "number"},
                        "location": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "zone", "fixture_key",
                        "lumens_per_fixture", "watts_per_fixture", "count",
                        "total_lumens", "target_lumens", "location", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "fixture_layout": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},              # F1, F2 ...
                        "fixture_key": {"type": "string"},
                        "use": {"type": "string"},              # ambient | task | accent
                        "x_ratio": {"type": "number"},
                        "y_ratio": {"type": "number"},
                        "mount": {"type": "string"},
                        "circuit_id": {"type": "string"},       # LC1 / LC2 ...
                    },
                    "required": [
                        "key", "fixture_key", "use",
                        "x_ratio", "y_ratio", "mount", "circuit_id",
                    ],
                    "additionalProperties": False,
                },
            },
            "lighting_circuits": {"type": "integer"},
            "outlets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},              # O1, O2 ...
                        "type": {"type": "string"},             # OUTLET_CATALOGUE key
                        "rating_a": {"type": "number"},
                        "phase": {"type": "string"},            # single | three | low_v | elv
                        "count": {"type": "integer"},
                        "location": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "type", "rating_a", "phase",
                        "count", "location", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "general_outlet_circuits": {"type": "integer"},
            "dedicated_circuits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},      # D1, D2 ...
                        "name": {"type": "string"},     # "AC dedicated", "Geyser dedicated"
                        "load_w": {"type": "number"},
                        "breaker_a": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "name", "load_w", "breaker_a", "rationale"],
                    "additionalProperties": False,
                },
            },
            "total_connected_load_kw": {"type": "number"},
            "diversity_assumptions": {
                "type": "object",
                "properties": {
                    "general_outlet_diversity": {"type": "number"},
                    "appliance_outlet_diversity": {"type": "number"},
                    "low_voltage_diversity": {"type": "number"},
                },
                "required": [
                    "general_outlet_diversity",
                    "appliance_outlet_diversity",
                    "low_voltage_diversity",
                ],
                "additionalProperties": False,
            },
            "panel": {
                "type": "object",
                "properties": {
                    "main_breaker_a": {"type": "number"},
                    "phase": {"type": "string"},        # "single_phase_230v" | "three_phase_415v"
                    "spare_capacity_pct": {"type": "number"},
                    "location": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "main_breaker_a", "phase", "spare_capacity_pct",
                    "location", "rationale",
                ],
                "additionalProperties": False,
            },
            "outlet_strategy": {"type": "string"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "ambient_lux_target", "task_lux_target", "power_density_w_per_m2",
            "total_lighting_load_w", "ambient_fixtures", "task_lighting",
            "fixture_layout", "lighting_circuits", "outlets",
            "general_outlet_circuits", "dedicated_circuits",
            "total_connected_load_kw", "diversity_assumptions",
            "panel", "outlet_strategy", "assumptions",
        ],
        "additionalProperties": False,
    }


def _plumbing_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "fixtures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},      # P1, P2 ...
                        "type": {"type": "string"},     # DFU_PER_FIXTURE key
                        "dfu": {"type": "integer"},
                        "wsfu_cold": {"type": "number"},
                        "wsfu_hot": {"type": "number"},
                        "wsfu_total": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "type", "dfu",
                        "wsfu_cold", "wsfu_hot", "wsfu_total", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "total_dfu": {"type": "integer"},
            "total_wsfu": {"type": "number"},
            "water_supply": {
                "type": "object",
                "properties": {
                    "demand_gpm": {"type": "number"},
                    "demand_lpm": {"type": "number"},
                    "curve": {"type": "string"},                # "hunter_flush_tank"
                    "supply_main_pipe_size_mm": {"type": "number"},
                    "hot_water_supply_pipe_size_mm": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "demand_gpm", "demand_lpm", "curve",
                    "supply_main_pipe_size_mm",
                    "hot_water_supply_pipe_size_mm", "rationale",
                ],
                "additionalProperties": False,
            },
            "main_drain_size_mm": {"type": "number"},
            "drain_size_rationale": {"type": "string"},
            "slope_per_metre": {"type": "number"},
            "slope_imperial": {"type": "string"},       # "1/4 inch per foot"
            "traps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},      # T1, T2 ...
                        "fixture_type": {"type": "string"},
                        "trap_mm": {"type": "number"},
                        "trap_type": {"type": "string"},
                        "seal_depth_mm": {"type": "number"},
                        "developed_length_m": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "fixture_type", "trap_mm", "trap_type",
                        "seal_depth_mm", "developed_length_m", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "vent_stack_size_mm": {"type": "number"},
            "vent_developed_length_m": {"type": "number"},
            "vent_terminal_height_above_roof_mm": {"type": "number"},
            "vent_loops": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},          # V1, V2 ...
                        "vent_type": {"type": "string"},    # VENT_TYPES_IN_SCOPE
                        "fixtures_served": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "branch_dfu": {"type": "integer"},
                        "vent_size_mm": {"type": "number"},
                        "loop_back_to": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "vent_type", "fixtures_served",
                        "branch_dfu", "vent_size_mm", "loop_back_to", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "water_demand_lpd_per_person": {"type": "number"},
            "water_demand_total_lpd": {"type": "number"},
            "water_demand_band_cited": {
                "type": "array",
                "items": {"type": "number"},      # [low, high]
            },
            "venting_strategy": {"type": "string"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "fixtures", "total_dfu", "total_wsfu",
            "water_supply",
            "main_drain_size_mm", "drain_size_rationale",
            "slope_per_metre", "slope_imperial",
            "traps",
            "vent_stack_size_mm", "vent_developed_length_m",
            "vent_terminal_height_above_roof_mm", "vent_loops",
            "water_demand_lpd_per_person",
            "water_demand_total_lpd", "water_demand_band_cited",
            "venting_strategy", "assumptions",
        ],
        "additionalProperties": False,
    }


def _cost_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "currency": {"type": "string"},
            "city_price_index": {"type": "number"},
            "systems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "system": {"type": "string"},        # hvac | electrical | plumbing
                        "system_key": {"type": "string"},    # cost band key
                        "rate_band_inr_m2": {
                            "type": "object",
                            "properties": {
                                "low": {"type": "number"},
                                "high": {"type": "number"},
                            },
                            "required": ["low", "high"],
                            "additionalProperties": False,
                        },
                        "area_m2": {"type": "number"},
                        "total_inr": {
                            "type": "object",
                            "properties": {
                                "low": {"type": "number"},
                                "high": {"type": "number"},
                            },
                            "required": ["low", "high"],
                            "additionalProperties": False,
                        },
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "system", "system_key", "rate_band_inr_m2",
                        "area_m2", "total_inr", "notes",
                    ],
                    "additionalProperties": False,
                },
            },
            "grand_total_inr": {
                "type": "object",
                "properties": {
                    "low": {"type": "number"},
                    "high": {"type": "number"},
                },
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "currency", "city_price_index", "systems",
            "grand_total_inr", "assumptions",
        ],
        "additionalProperties": False,
    }


MEP_SPEC_SCHEMA: dict[str, Any] = {
    "name": "mep_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "room_name": {"type": "string"},
                    "room_use_type": {"type": "string"},
                    "city": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "city_price_index": {"type": "number"},
                },
                "required": [
                    "project", "room_name", "room_use_type",
                    "city", "date_iso", "city_price_index",
                ],
                "additionalProperties": False,
            },
            "geometry": {
                "type": "object",
                "properties": {
                    "length_m": {"type": "number"},
                    "width_m": {"type": "number"},
                    "height_m": {"type": "number"},
                    "area_m2": {"type": "number"},
                    "volume_m3": {"type": "number"},
                },
                "required": [
                    "length_m", "width_m", "height_m", "area_m2", "volume_m3",
                ],
                "additionalProperties": False,
            },
            "hvac": _hvac_block_schema(),
            "electrical": _electrical_block_schema(),
            "plumbing": _plumbing_block_schema(),
            "cost": _cost_block_schema(),
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "geometry", "hvac", "electrical",
            "plumbing", "cost", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: MEPSpecRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Room: {req.room_name} (use: {req.room_use_type})\n"
        f"- Dimensions: {req.dimensions.length_m} m × {req.dimensions.width_m} m × {req.dimensions.height_m} m\n"
        f"- Occupancy: {req.occupancy or '(not specified)'}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Theme: {req.theme or '(not specified)'}\n"
        f"- Plumbing fixtures declared: {', '.join(req.fixtures) or '(none)'}\n"
        f"- Date (UTC ISO): {today}\n"
        f"- Sections requested: {', '.join(req.sections or ['hvac','electrical','plumbing','cost'])}\n\n"
        "Produce the mep_spec JSON. Fill the header + geometry + hvac + "
        "electrical + plumbing + cost blocks. Snap every number to the "
        "BRD catalogues — never invent ACH values, tonnages, equipment "
        "ladders, duct charts, lux levels, power densities, circuit "
        "ratings, DFU values, pipe sizes, water demand bands, or cost "
        "bands."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _approx_eq(a: Any, b: Any, tol: float = 1e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _within(v: Any, band: list | tuple, *, tol: float = 1e-6) -> bool:
    try:
        lo, hi = float(band[0]), float(band[1])
        return lo - tol <= float(v) <= hi + tol
    except (TypeError, ValueError, IndexError):
        return False


def _validate_hvac(spec: dict[str, Any], knowledge: dict[str, Any], out: dict[str, list[Any]]) -> None:
    block = spec.get("hvac") or {}
    geom = knowledge.get("geometry") or {}
    pre = knowledge.get("hvac_pre_calc") or {}
    brd = knowledge.get("hvac_brd") or {}
    use = (knowledge.get("project") or {}).get("room_use_type")

    # Volume.
    if not _approx_eq(block.get("room_volume_m3"), geom.get("volume_m3"), tol=0.05):
        out["bad_room_volume"].append({
            "expected": geom.get("volume_m3"), "actual": block.get("room_volume_m3"),
        })

    # ACH.
    expected_ach = brd.get("ach_table", {}).get(use)
    if expected_ach is not None and not _approx_eq(block.get("ach_required"), expected_ach):
        out["bad_ach"].append({
            "use": use, "expected": expected_ach, "actual": block.get("ach_required"),
        })

    # CFM.
    if pre.get("cfm_total") is not None and not _approx_eq(
        block.get("cfm_total"), pre["cfm_total"], tol=0.5
    ):
        out["bad_cfm_total"].append({
            "expected": pre["cfm_total"], "actual": block.get("cfm_total"),
        })

    # Cooling.
    cooling = block.get("cooling") or {}
    if pre.get("cooling_tonnage") is not None and not _approx_eq(
        cooling.get("tonnage"), pre["cooling_tonnage"], tol=0.05
    ):
        out["bad_tonnage"].append({
            "expected": pre["cooling_tonnage"], "actual": cooling.get("tonnage"),
        })
    if cooling.get("tonnage") is not None:
        expected_btu = float(cooling["tonnage"]) * brd.get("btu_per_tr", 12000)
        if not _approx_eq(cooling.get("btu_per_hr"), expected_btu, tol=1.0):
            out["bad_btu_per_hr"].append({
                "expected": round(expected_btu, 0), "actual": cooling.get("btu_per_hr"),
            })
        expected_kw = float(cooling["tonnage"]) * brd.get("kw_per_tr", 3.517)
        if not _approx_eq(cooling.get("kw_thermal"), expected_kw, tol=0.05):
            out["bad_kw_thermal"].append({
                "expected": round(expected_kw, 2), "actual": cooling.get("kw_thermal"),
            })

    # Equipment.
    pick = pre.get("equipment_pick") or {}
    eq = block.get("equipment") or {}
    if pick.get("selected_tr") is not None and not _approx_eq(
        eq.get("selected_tr"), pick["selected_tr"]
    ):
        out["bad_equipment_tr"].append({
            "expected": pick["selected_tr"], "actual": eq.get("selected_tr"),
        })
    if pick.get("type") and eq.get("type") and eq["type"] != pick["type"]:
        out["bad_equipment_type"].append({
            "expected": pick["type"], "actual": eq.get("type"),
        })
    unit_count = eq.get("unit_count") or 0
    if unit_count < 1:
        out["bad_equipment_unit_count"].append(unit_count)
    if cooling.get("tonnage") and eq.get("selected_tr"):
        if float(eq["selected_tr"]) * max(unit_count, 1) + 1e-6 < float(cooling["tonnage"]):
            out["equipment_under_load"].append({
                "load_tr": cooling["tonnage"],
                "installed_tr": float(eq["selected_tr"]) * max(unit_count, 1),
            })

    # Ductwork.
    duct = block.get("ductwork") or {}
    shape = (duct.get("shape") or "").lower()
    if shape not in DUCT_SHAPE_IN_SCOPE:
        out["bad_duct_shape"].append(shape or "<missing>")
    if shape == "round":
        if pre.get("duct_round_diameter_mm") is not None:
            if not _approx_eq(duct.get("diameter_mm"), pre["duct_round_diameter_mm"], tol=1.0):
                out["bad_duct_diameter"].append({
                    "expected": pre["duct_round_diameter_mm"], "actual": duct.get("diameter_mm"),
                })
    elif shape == "rectangular":
        rect = pre.get("duct_rectangular_mm") or {}
        ew = rect.get("width") or 0
        eh = rect.get("height") or 0
        if duct.get("width_mm") is None or float(duct.get("width_mm") or 0) + 1e-6 < float(ew):
            out["duct_rect_undersized"].append({
                "axis": "width", "expected_min_mm": ew, "actual_mm": duct.get("width_mm"),
            })
        if duct.get("height_mm") is None or float(duct.get("height_mm") or 0) + 1e-6 < float(eh):
            out["duct_rect_undersized"].append({
                "axis": "height", "expected_min_mm": eh, "actual_mm": duct.get("height_mm"),
            })
    vclass = (duct.get("velocity_class") or "").lower()
    if vclass not in DUCT_CLASSES_IN_SCOPE:
        out["bad_duct_velocity_class"].append(vclass or "<missing>")
    band = brd.get("duct_velocity_m_s", {}).get(vclass)
    if band and not _within(duct.get("velocity_m_s"), band):
        out["duct_velocity_out_of_band"].append({
            "class": vclass, "band": list(band), "actual": duct.get("velocity_m_s"),
        })

    # Supply registers.
    supply = block.get("supply_registers") or []
    bad_supply_types = [
        s.get("type") for s in supply
        if (s.get("type") or "") not in SUPPLY_REGISTER_KEYS_IN_SCOPE
    ]
    if bad_supply_types:
        out["bad_supply_register_types"].extend(bad_supply_types)
    supply_cfm = 0.0
    for s in supply:
        rating = brd.get("register_cfm_rating", {}).get(s.get("type"))
        if rating is None:
            continue
        count = int(s.get("count") or 0)
        supply_cfm += rating * max(count, 0)
        cfm_each = s.get("cfm_each")
        if cfm_each is not None and not _approx_eq(cfm_each, rating, tol=1.0):
            out["bad_supply_cfm_each"].append({
                "type": s.get("type"), "expected": rating, "actual": cfm_each,
            })
    cfm_total = block.get("cfm_total") or pre.get("cfm_total") or 0
    if cfm_total and supply_cfm + 1e-6 < float(cfm_total):
        out["supply_under_cfm"].append({
            "supply_total_cfm": supply_cfm, "required_cfm": cfm_total,
        })

    # Return registers.
    returns = block.get("return_registers") or []
    bad_return_types = [
        r.get("type") for r in returns
        if (r.get("type") or "") not in RETURN_REGISTER_KEYS_IN_SCOPE
    ]
    if bad_return_types:
        out["bad_return_register_types"].extend(bad_return_types)
    return_cfm = 0.0
    for r in returns:
        rating = brd.get("register_cfm_rating", {}).get(r.get("type"))
        if rating is None:
            continue
        count = int(r.get("count") or 0)
        return_cfm += rating * max(count, 0)
    if cfm_total and return_cfm + 1e-6 < 0.85 * float(cfm_total):
        out["return_under_cfm"].append({
            "return_total_cfm": return_cfm,
            "required_min_cfm": round(0.85 * float(cfm_total), 1),
        })


def _validate_electrical(spec: dict[str, Any], knowledge: dict[str, Any], out: dict[str, list[Any]]) -> None:
    block = spec.get("electrical") or {}
    pre = knowledge.get("electrical_pre_calc") or {}
    brd = knowledge.get("electrical_brd") or {}
    geom = knowledge.get("geometry") or {}
    fixture_cat = brd.get("fixture_catalogue", {}) or {}
    outlet_cat = brd.get("outlet_catalogue", {}) or {}
    layout_rules = brd.get("lighting_layout_rules", {}) or {}

    if pre.get("ambient_lux_target") is not None and not _approx_eq(
        block.get("ambient_lux_target"), pre["ambient_lux_target"]
    ):
        out["bad_ambient_lux"].append({
            "expected": pre["ambient_lux_target"], "actual": block.get("ambient_lux_target"),
        })
    if pre.get("task_lux_target") is not None and not _approx_eq(
        block.get("task_lux_target"), pre["task_lux_target"]
    ):
        out["bad_task_lux"].append({
            "expected": pre["task_lux_target"], "actual": block.get("task_lux_target"),
        })
    expected_density = brd.get("power_density_w_per_m2", {}).get(pre.get("power_use_mapped"))
    if expected_density is not None and not _approx_eq(
        block.get("power_density_w_per_m2"), expected_density
    ):
        out["bad_power_density"].append({
            "use": pre.get("power_use_mapped"),
            "expected": expected_density, "actual": block.get("power_density_w_per_m2"),
        })
    if expected_density is not None and geom.get("area_m2") is not None:
        expected_load = float(geom["area_m2"]) * float(expected_density)
        if not _approx_eq(block.get("total_lighting_load_w"), expected_load, tol=1.0):
            out["bad_lighting_load"].append({
                "expected": round(expected_load, 0), "actual": block.get("total_lighting_load_w"),
            })

    # Ambient fixtures.
    amb = block.get("ambient_fixtures") or {}
    fkey = amb.get("type")
    if fkey not in fixture_cat:
        out["bad_ambient_fixture_type"].append(fkey or "<missing>")
    else:
        spec_f = fixture_cat[fkey]
        if spec_f.get("use") and spec_f["use"] not in {"ambient", "accent"}:
            out["ambient_fixture_wrong_use"].append({"type": fkey, "use": spec_f.get("use")})
        if not _approx_eq(amb.get("lumens_per_fixture"), spec_f.get("lumens"), tol=1.0):
            out["bad_ambient_lumens"].append({
                "type": fkey, "expected": spec_f.get("lumens"),
                "actual": amb.get("lumens_per_fixture"),
            })
        if not _approx_eq(amb.get("watts_per_fixture"), spec_f.get("watts"), tol=0.5):
            out["bad_ambient_watts"].append({
                "type": fkey, "expected": spec_f.get("watts"),
                "actual": amb.get("watts_per_fixture"),
            })
        if (amb.get("count") or 0) < 1:
            out["ambient_count_too_low"].append(amb.get("count"))
        # Lux design must hit ambient_lux_target.
        if pre.get("ambient_lux_target") and amb.get("lux_design") is not None:
            if float(amb["lux_design"]) + 1e-6 < float(pre["ambient_lux_target"]):
                out["ambient_lux_below_target"].append({
                    "target": pre["ambient_lux_target"], "design": amb["lux_design"],
                })
        # Spacing rule.
        sh = amb.get("spacing_S_to_H")
        max_sh = layout_rules.get("downlight_S_to_H_ratio_max", 1.2)
        if sh is not None and float(sh) > float(max_sh) + 1e-6:
            out["ambient_sh_above_max"].append({"max": max_sh, "actual": sh})
        # Perimeter offset.
        po_expected = layout_rules.get("perimeter_offset_m")
        if po_expected is not None and not _approx_eq(amb.get("perimeter_offset_m"), po_expected, tol=0.05):
            out["bad_perimeter_offset"].append({
                "expected": po_expected, "actual": amb.get("perimeter_offset_m"),
            })

    # Task lighting — must cover every recipe zone for this room use.
    recipe = pre.get("task_lighting_recipe_for_use") or []
    recipe_zones = {r.get("zone"): r for r in recipe}
    task_block = block.get("task_lighting") or []
    seen_zones = {t.get("zone"): t for t in task_block}
    for zone, r in recipe_zones.items():
        t = seen_zones.get(zone)
        if not t:
            out["task_zone_missing"].append(zone)
            continue
        fkey = t.get("fixture_key")
        if fkey not in fixture_cat:
            out["bad_task_fixture_key"].append({"zone": zone, "fixture_key": fkey})
            continue
        cat = fixture_cat[fkey]
        if not _approx_eq(t.get("lumens_per_fixture"), cat.get("lumens"), tol=1.0):
            out["bad_task_lumens"].append({
                "zone": zone, "expected": cat.get("lumens"),
                "actual": t.get("lumens_per_fixture"),
            })
        if not _approx_eq(t.get("watts_per_fixture"), cat.get("watts"), tol=0.5):
            out["bad_task_watts"].append({
                "zone": zone, "expected": cat.get("watts"),
                "actual": t.get("watts_per_fixture"),
            })
        count = int(t.get("count") or 0)
        expected_total = count * (cat.get("lumens") or 0)
        if not _approx_eq(t.get("total_lumens"), expected_total, tol=1.0):
            out["bad_task_total_lumens"].append({
                "zone": zone, "expected": expected_total,
                "actual": t.get("total_lumens"),
            })
        target = r.get("target_lumens") or 0
        if expected_total + 1e-6 < target:
            out["task_total_below_target"].append({
                "zone": zone, "target": target, "actual_total_lumens": expected_total,
            })

    # Fixture layout coverage (count-based, not per-fixture identity).
    layout = block.get("fixture_layout") or []
    expected_total_fixtures = (amb.get("count") or 0) + sum(
        int(t.get("count") or 0) for t in task_block
    )
    layout_total = sum(1 for _ in layout)  # one layout entry per fixture group; many designs collapse
    # Each entry's x_ratio / y_ratio in [0,1], mount matches catalogue.
    bad_layout_ratio: list[str] = []
    bad_layout_mount: list[dict] = []
    for f in layout:
        for axis in ("x_ratio", "y_ratio"):
            v = f.get(axis)
            if v is None or not (0.0 <= float(v) <= 1.0):
                bad_layout_ratio.append(f"{f.get('key')}.{axis}")
        cat = fixture_cat.get(f.get("fixture_key"))
        if cat and f.get("mount") and f["mount"] != cat.get("mount"):
            bad_layout_mount.append({
                "key": f.get("key"), "expected": cat.get("mount"),
                "actual": f.get("mount"),
            })
    if bad_layout_ratio:
        out["bad_layout_ratios"].extend(bad_layout_ratio)
    if bad_layout_mount:
        out["bad_layout_mount"].extend(bad_layout_mount)
    if expected_total_fixtures and layout_total < 1:
        out["fixture_layout_empty"].append({
            "fixtures_declared": expected_total_fixtures, "layout_entries": 0,
        })

    # Lighting circuits.
    circuit_max = brd.get("circuit_load_w", {}).get("lighting_circuit_max", 1500)
    load_w = block.get("total_lighting_load_w") or 0
    expected_min_circuits = max(1, math.ceil(float(load_w) / float(circuit_max))) if load_w else 1
    if (block.get("lighting_circuits") or 0) < expected_min_circuits:
        out["lighting_circuits_below_min"].append({
            "expected_min": expected_min_circuits, "actual": block.get("lighting_circuits"),
        })

    # Outlets.
    outlets = block.get("outlets") or []
    bad_outlet_types: list[str] = []
    bad_outlet_rating: list[dict] = []
    bad_outlet_phase: list[dict] = []
    for o in outlets:
        t = o.get("type")
        cat = outlet_cat.get(t)
        if cat is None:
            bad_outlet_types.append(t or "<missing>")
            continue
        if o.get("rating_a") is not None and not _approx_eq(o["rating_a"], cat.get("rating_a"), tol=0.5):
            bad_outlet_rating.append({"type": t, "expected": cat.get("rating_a"), "actual": o["rating_a"]})
        if o.get("phase") and o["phase"] != cat.get("phase"):
            bad_outlet_phase.append({"type": t, "expected": cat.get("phase"), "actual": o["phase"]})
    if bad_outlet_types:
        out["bad_outlet_types"].extend(bad_outlet_types)
    if bad_outlet_rating:
        out["bad_outlet_rating"].extend(bad_outlet_rating)
    if bad_outlet_phase:
        out["bad_outlet_phase"].extend(bad_outlet_phase)

    # Minimum general-outlet count.
    general_count = sum(
        int(o.get("count") or 0) for o in outlets
        if o.get("type") == "5_15A_universal"
    )
    expected_general = (pre.get("outlet_pick") or {}).get("general_outlets") or 0
    if expected_general and general_count < expected_general:
        out["general_outlets_below_min"].append({
            "expected_min": expected_general, "actual": general_count,
        })

    # Total connected load (kW). Rebuild to verify.
    diversity = block.get("diversity_assumptions") or {}
    div_general = float(diversity.get("general_outlet_diversity") or 0.4)
    div_appliance = float(diversity.get("appliance_outlet_diversity") or 0.6)
    div_lv = float(diversity.get("low_voltage_diversity") or 0.0)
    outlet_load_w = 0.0
    for o in outlets:
        cat = outlet_cat.get(o.get("type")) or {}
        unit = float(cat.get("circuit_load_w") or 0)
        cnt = float(o.get("count") or 0)
        phase_kind = cat.get("phase")
        use_kind = cat.get("use")
        if phase_kind in {"low_v", "elv"}:
            outlet_load_w += unit * cnt * div_lv
        elif use_kind == "general_outlet":
            outlet_load_w += unit * cnt * div_general
        else:
            outlet_load_w += unit * cnt * div_appliance
    dedicated_w = sum(float(d.get("load_w") or 0) for d in (block.get("dedicated_circuits") or []))
    expected_kw = (float(load_w) + outlet_load_w + dedicated_w) / 1000.0
    if block.get("total_connected_load_kw") is not None and not _approx_eq(
        block["total_connected_load_kw"], expected_kw, tol=0.2
    ):
        out["bad_total_connected_load_kw"].append({
            "expected_approx": round(expected_kw, 2),
            "actual": block.get("total_connected_load_kw"),
            "diversity_used": {"general": div_general, "appliance": div_appliance, "lv": div_lv},
        })

    panel = block.get("panel") or {}
    if (panel.get("spare_capacity_pct") or 0) + 1e-6 < 20:
        out["panel_spare_below_20"].append(panel.get("spare_capacity_pct"))
    if panel.get("phase") not in {"single_phase_230v", "three_phase_415v"}:
        out["bad_panel_phase"].append(panel.get("phase"))
    # Phase choice consistency: > 7 kW should be three-phase.
    if block.get("total_connected_load_kw") is not None:
        if float(block["total_connected_load_kw"]) > 7 and panel.get("phase") != "three_phase_415v":
            out["panel_phase_inconsistent_with_load"].append({
                "load_kw": block["total_connected_load_kw"], "phase": panel.get("phase"),
            })

    catalogue_loads = set(brd.get("circuit_load_w", {}).values())
    for d in block.get("dedicated_circuits") or []:
        load = d.get("load_w")
        if load is None or int(load) not in catalogue_loads:
            out["bad_dedicated_load"].append({"key": d.get("key"), "load_w": load})


def _validate_plumbing(spec: dict[str, Any], knowledge: dict[str, Any], out: dict[str, list[Any]]) -> None:
    block = spec.get("plumbing") or {}
    brd = knowledge.get("plumbing_brd") or {}
    pre = knowledge.get("plumbing_pre_calc") or {}
    declared = (knowledge.get("project") or {}).get("fixtures_declared") or []
    wsfu_cat = brd.get("wsfu_per_fixture", {}) or {}
    trap_cat = brd.get("trap_size_mm_per_fixture", {}) or {}

    fixtures = block.get("fixtures") or []
    if declared and not fixtures:
        out["plumbing_missing_fixtures"].append({"declared": declared})

    bad_fixture_types: list[str] = []
    bad_dfu: list[dict] = []
    bad_wsfu: list[dict] = []
    total_dfu = 0
    total_wsfu = 0.0
    for f in fixtures:
        t = (f.get("type") or "").strip()
        if t not in DFU_FIXTURE_KEYS_IN_SCOPE:
            bad_fixture_types.append(t)
            continue
        expected = brd.get("dfu_per_fixture", {}).get(t)
        if expected is not None and f.get("dfu") != expected:
            bad_dfu.append({"type": t, "expected": expected, "actual": f.get("dfu")})
        total_dfu += int(f.get("dfu") or 0)

        wcat = wsfu_cat.get(t)
        if wcat is not None:
            for fld in ("cold", "hot", "total"):
                expected_w = wcat.get(fld)
                actual_w = f.get(f"wsfu_{fld}")
                if expected_w is not None and not _approx_eq(actual_w, expected_w, tol=0.05):
                    bad_wsfu.append({
                        "type": t, "field": f"wsfu_{fld}",
                        "expected": expected_w, "actual": actual_w,
                    })
            total_wsfu += float(wcat.get("total") or 0)
    if bad_fixture_types:
        out["bad_fixture_types"].extend(bad_fixture_types)
    if bad_dfu:
        out["bad_dfu_values"].extend(bad_dfu)
    if bad_wsfu:
        out["bad_wsfu_values"].extend(bad_wsfu)
    if fixtures and block.get("total_dfu") != total_dfu:
        out["bad_total_dfu"].append({"expected": total_dfu, "actual": block.get("total_dfu")})
    if fixtures and not _approx_eq(block.get("total_wsfu"), total_wsfu, tol=0.1):
        out["bad_total_wsfu"].append({"expected": round(total_wsfu, 2), "actual": block.get("total_wsfu")})

    # Water supply (Hunter's curve).
    supply = block.get("water_supply") or {}
    expected_summary = pre.get("supply_summary") or {}
    if expected_summary.get("demand_gpm") is not None and not _approx_eq(
        supply.get("demand_gpm"), expected_summary["demand_gpm"], tol=0.05
    ):
        out["bad_demand_gpm"].append({
            "expected": expected_summary["demand_gpm"], "actual": supply.get("demand_gpm"),
        })
    if supply.get("demand_gpm") is not None:
        expected_lpm = round(float(supply["demand_gpm"]) * brd.get("gpm_to_lpm", 3.78541), 2)
        if not _approx_eq(supply.get("demand_lpm"), expected_lpm, tol=0.1):
            out["bad_demand_lpm"].append({
                "expected": expected_lpm, "actual": supply.get("demand_lpm"),
            })
    expected_supply_pipe = None
    for row in brd.get("supply_pipe_size_mm_by_gpm") or []:
        if (supply.get("demand_gpm") or 0) <= row.get("gpm_max", 0):
            expected_supply_pipe = row.get("pipe_mm")
            break
    if supply.get("demand_gpm") and expected_supply_pipe is not None:
        if supply.get("supply_main_pipe_size_mm") != expected_supply_pipe:
            out["bad_supply_main_pipe"].append({
                "demand_gpm": supply.get("demand_gpm"),
                "expected_mm": expected_supply_pipe,
                "actual_mm": supply.get("supply_main_pipe_size_mm"),
            })
    if (supply.get("curve") or "") not in {"hunter_flush_tank"}:
        out["bad_supply_curve"].append(supply.get("curve") or "<missing>")

    # Drain.
    expected_pipe = None
    for row in brd.get("pipe_size_mm_by_dfu") or []:
        if total_dfu <= row.get("dfu_max", 0):
            expected_pipe = row.get("pipe_mm")
            break
    if total_dfu and expected_pipe is not None:
        if block.get("main_drain_size_mm") != expected_pipe:
            out["bad_main_drain_size"].append({
                "total_dfu": total_dfu, "expected_mm": expected_pipe,
                "actual_mm": block.get("main_drain_size_mm"),
            })

    # Slope.
    slope_pref = brd.get("slope_requirement", {}).get("horizontal_drain_preferred", {}).get("ratio")
    slope_min = brd.get("slope_requirement", {}).get("horizontal_drain_min", {}).get("ratio")
    slope_actual = block.get("slope_per_metre")
    if slope_actual is not None and slope_pref is not None:
        if not _approx_eq(slope_actual, slope_pref) and not _approx_eq(slope_actual, slope_min):
            out["bad_slope"].append({
                "expected_one_of": [slope_pref, slope_min], "actual": slope_actual,
            })
    # Imperial string consistency.
    expected_imperial = None
    if _approx_eq(slope_actual, slope_pref):
        expected_imperial = brd.get("slope_requirement", {}).get("horizontal_drain_preferred", {}).get("imperial")
    elif _approx_eq(slope_actual, slope_min):
        expected_imperial = brd.get("slope_requirement", {}).get("horizontal_drain_min", {}).get("imperial")
    if expected_imperial and block.get("slope_imperial") and block["slope_imperial"] != expected_imperial:
        out["bad_slope_imperial"].append({
            "expected": expected_imperial, "actual": block.get("slope_imperial"),
        })

    # Traps — one per declared fixture, sizes match catalogue.
    traps = block.get("traps") or []
    seen_trap_fixtures = {t.get("fixture_type") for t in traps}
    for f in fixtures:
        if f.get("type") and f["type"] not in seen_trap_fixtures:
            out["trap_missing_for_fixture"].append(f["type"])
    bad_trap_sizes: list[dict] = []
    bad_trap_types: list[dict] = []
    bad_seal: list[dict] = []
    s_traps_specified: list[str] = []
    for t in traps:
        ftype = t.get("fixture_type")
        cat = trap_cat.get(ftype)
        if not cat:
            continue
        if not _approx_eq(t.get("trap_mm"), cat.get("trap_mm"), tol=0.5):
            bad_trap_sizes.append({
                "fixture": ftype, "expected_mm": cat.get("trap_mm"),
                "actual_mm": t.get("trap_mm"),
            })
        ttype = (t.get("trap_type") or "")
        if ttype != cat.get("trap_type"):
            bad_trap_types.append({
                "fixture": ftype, "expected": cat.get("trap_type"), "actual": ttype,
            })
        if "s_trap" in ttype.lower() and "p_trap" not in ttype.lower():
            s_traps_specified.append(f"{ftype} -> {ttype}")
        seal = t.get("seal_depth_mm")
        if seal is None or float(seal) + 1e-6 < 50:
            bad_seal.append({"fixture": ftype, "actual_mm": seal, "min_mm": 50})
    if bad_trap_sizes:
        out["bad_trap_sizes"].extend(bad_trap_sizes)
    if bad_trap_types:
        out["bad_trap_types"].extend(bad_trap_types)
    if bad_seal:
        out["bad_trap_seal"].extend(bad_seal)
    if s_traps_specified:
        out["s_trap_specified"].extend(s_traps_specified)

    # Vent stack.
    expected_vent_size = None
    vent_len = float(block.get("vent_developed_length_m") or 0)
    for row in brd.get("vent_stack_size_by_dfu") or []:
        if total_dfu <= row.get("dfu_max", 0) and vent_len <= row.get("max_length_m", 0):
            expected_vent_size = row.get("vent_mm")
            break
    if total_dfu and expected_vent_size is not None:
        if block.get("vent_stack_size_mm") != expected_vent_size:
            out["bad_vent_stack_size"].append({
                "total_dfu": total_dfu, "developed_length_m": vent_len,
                "expected_mm": expected_vent_size,
                "actual_mm": block.get("vent_stack_size_mm"),
            })
    if total_dfu and (block.get("vent_terminal_height_above_roof_mm") or 0) + 1e-6 < 300:
        out["vent_terminal_too_low"].append({
            "min_mm": 300, "actual_mm": block.get("vent_terminal_height_above_roof_mm"),
        })

    # Vent loops.
    bad_vent_types: list[str] = []
    for v in block.get("vent_loops") or []:
        vt = (v.get("vent_type") or "")
        if vt not in VENT_TYPES_IN_SCOPE:
            bad_vent_types.append(vt or "<missing>")
    if bad_vent_types:
        out["bad_vent_types"].extend(bad_vent_types)


def _validate_cost(spec: dict[str, Any], knowledge: dict[str, Any], out: dict[str, list[Any]]) -> None:
    block = spec.get("cost") or {}
    bands = knowledge.get("cost_bands") or {}
    picks = knowledge.get("system_picks") or {}
    geom = knowledge.get("geometry") or {}
    index = knowledge.get("city_price_index") or 1.0

    if (block.get("currency") or "").upper() != "INR":
        out["bad_currency"].append(block.get("currency"))
    if not _approx_eq(block.get("city_price_index"), index, tol=0.0001):
        out["bad_city_index"].append({
            "expected": index, "actual": block.get("city_price_index"),
        })

    systems = block.get("systems") or []
    seen = {s.get("system"): s for s in systems}
    for sys_name in ("hvac", "electrical", "plumbing"):
        s = seen.get(sys_name)
        expected_key = picks.get(sys_name)
        if not s:
            out["missing_cost_system"].append(sys_name)
            continue
        if expected_key and s.get("system_key") != expected_key:
            out["bad_cost_system_key"].append({
                "system": sys_name, "expected": expected_key, "actual": s.get("system_key"),
            })
        rate = (bands.get(sys_name) or {}).get("rate_inr_m2") or {}
        actual_rate = s.get("rate_band_inr_m2") or {}
        if rate.get("low") is not None and not _approx_eq(actual_rate.get("low"), rate.get("low")):
            out["bad_cost_rate_low"].append({"system": sys_name, "expected": rate.get("low"), "actual": actual_rate.get("low")})
        if rate.get("high") is not None and not _approx_eq(actual_rate.get("high"), rate.get("high")):
            out["bad_cost_rate_high"].append({"system": sys_name, "expected": rate.get("high"), "actual": actual_rate.get("high")})

        area = geom.get("area_m2") or 0
        for side in ("low", "high"):
            expected_total = round(float(rate.get(side) or 0) * float(area) * float(index), 0)
            actual_total = (s.get("total_inr") or {}).get(side)
            if actual_total is not None and not _approx_eq(actual_total, expected_total, tol=2.0):
                out["bad_cost_total"].append({
                    "system": sys_name, "side": side,
                    "expected": expected_total, "actual": actual_total,
                })

    grand = block.get("grand_total_inr") or {}
    for side in ("low", "high"):
        sum_side = sum(
            (s.get("total_inr") or {}).get(side) or 0 for s in systems
        )
        if grand.get(side) is not None and not _approx_eq(grand.get(side), sum_side, tol=2.0):
            out["bad_grand_total"].append({
                "side": side, "expected": sum_side, "actual": grand.get(side),
            })


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, list[Any]] = {
        # HVAC
        "bad_room_volume": [],
        "bad_ach": [],
        "bad_cfm_total": [],
        "bad_tonnage": [],
        "bad_btu_per_hr": [],
        "bad_kw_thermal": [],
        "bad_equipment_tr": [],
        "bad_equipment_type": [],
        "bad_equipment_unit_count": [],
        "equipment_under_load": [],
        "bad_duct_shape": [],
        "bad_duct_diameter": [],
        "duct_rect_undersized": [],
        "bad_duct_velocity_class": [],
        "duct_velocity_out_of_band": [],
        "bad_supply_register_types": [],
        "bad_supply_cfm_each": [],
        "supply_under_cfm": [],
        "bad_return_register_types": [],
        "return_under_cfm": [],
        # Electrical
        "bad_ambient_lux": [],
        "bad_task_lux": [],
        "bad_power_density": [],
        "bad_lighting_load": [],
        "bad_ambient_fixture_type": [],
        "ambient_fixture_wrong_use": [],
        "bad_ambient_lumens": [],
        "bad_ambient_watts": [],
        "ambient_count_too_low": [],
        "ambient_lux_below_target": [],
        "ambient_sh_above_max": [],
        "bad_perimeter_offset": [],
        "task_zone_missing": [],
        "bad_task_fixture_key": [],
        "bad_task_lumens": [],
        "bad_task_watts": [],
        "bad_task_total_lumens": [],
        "task_total_below_target": [],
        "bad_layout_ratios": [],
        "bad_layout_mount": [],
        "fixture_layout_empty": [],
        "bad_outlet_types": [],
        "bad_outlet_rating": [],
        "bad_outlet_phase": [],
        "general_outlets_below_min": [],
        "bad_total_connected_load_kw": [],
        "panel_phase_inconsistent_with_load": [],
        "lighting_circuits_below_min": [],
        "panel_spare_below_20": [],
        "bad_panel_phase": [],
        "bad_dedicated_load": [],
        # Plumbing
        "plumbing_missing_fixtures": [],
        "bad_fixture_types": [],
        "bad_dfu_values": [],
        "bad_wsfu_values": [],
        "bad_total_dfu": [],
        "bad_total_wsfu": [],
        "bad_demand_gpm": [],
        "bad_demand_lpm": [],
        "bad_supply_main_pipe": [],
        "bad_supply_curve": [],
        "bad_main_drain_size": [],
        "bad_slope": [],
        "bad_slope_imperial": [],
        "trap_missing_for_fixture": [],
        "bad_trap_sizes": [],
        "bad_trap_types": [],
        "bad_trap_seal": [],
        "s_trap_specified": [],
        "bad_vent_stack_size": [],
        "vent_terminal_too_low": [],
        "bad_vent_types": [],
        # Cost
        "bad_currency": [],
        "bad_city_index": [],
        "missing_cost_system": [],
        "bad_cost_system_key": [],
        "bad_cost_rate_low": [],
        "bad_cost_rate_high": [],
        "bad_cost_total": [],
        "bad_grand_total": [],
    }

    _validate_hvac(spec, knowledge, out)
    _validate_electrical(spec, knowledge, out)
    _validate_plumbing(spec, knowledge, out)
    _validate_cost(spec, knowledge, out)

    return {
        # HVAC
        "room_volume_matches_geometry": not out["bad_room_volume"],
        "bad_room_volume": out["bad_room_volume"],
        "ach_matches_brd": not out["bad_ach"],
        "bad_ach": out["bad_ach"],
        "cfm_total_matches_pre_calc": not out["bad_cfm_total"],
        "bad_cfm_total": out["bad_cfm_total"],
        "tonnage_matches_pre_calc": not out["bad_tonnage"],
        "bad_tonnage": out["bad_tonnage"],
        "btu_per_hr_matches_tonnage": not out["bad_btu_per_hr"],
        "bad_btu_per_hr": out["bad_btu_per_hr"],
        "kw_thermal_matches_tonnage": not out["bad_kw_thermal"],
        "bad_kw_thermal": out["bad_kw_thermal"],
        "equipment_tr_matches_pick": not out["bad_equipment_tr"],
        "bad_equipment_tr": out["bad_equipment_tr"],
        "equipment_type_matches_pick": not out["bad_equipment_type"],
        "bad_equipment_type": out["bad_equipment_type"],
        "equipment_unit_count_valid": not out["bad_equipment_unit_count"],
        "bad_equipment_unit_count": out["bad_equipment_unit_count"],
        "equipment_meets_load": not out["equipment_under_load"],
        "equipment_under_load": out["equipment_under_load"],
        "duct_shape_valid": not out["bad_duct_shape"],
        "bad_duct_shape": out["bad_duct_shape"],
        "duct_diameter_matches_chart": not out["bad_duct_diameter"],
        "bad_duct_diameter": out["bad_duct_diameter"],
        "duct_rectangular_meets_size": not out["duct_rect_undersized"],
        "duct_rect_undersized": out["duct_rect_undersized"],
        "duct_velocity_class_valid": not out["bad_duct_velocity_class"],
        "bad_duct_velocity_class": out["bad_duct_velocity_class"],
        "duct_velocity_in_band": not out["duct_velocity_out_of_band"],
        "duct_velocity_out_of_band": out["duct_velocity_out_of_band"],
        "supply_register_types_valid": not out["bad_supply_register_types"],
        "bad_supply_register_types": out["bad_supply_register_types"],
        "supply_cfm_each_matches_catalogue": not out["bad_supply_cfm_each"],
        "bad_supply_cfm_each": out["bad_supply_cfm_each"],
        "supply_total_cfm_meets_load": not out["supply_under_cfm"],
        "supply_under_cfm": out["supply_under_cfm"],
        "return_register_types_valid": not out["bad_return_register_types"],
        "bad_return_register_types": out["bad_return_register_types"],
        "return_total_cfm_meets_minimum": not out["return_under_cfm"],
        "return_under_cfm": out["return_under_cfm"],
        # Electrical
        "ambient_lux_matches_brd": not out["bad_ambient_lux"],
        "bad_ambient_lux": out["bad_ambient_lux"],
        "task_lux_matches_brd": not out["bad_task_lux"],
        "bad_task_lux": out["bad_task_lux"],
        "power_density_matches_brd": not out["bad_power_density"],
        "bad_power_density": out["bad_power_density"],
        "lighting_load_matches_density": not out["bad_lighting_load"],
        "bad_lighting_load": out["bad_lighting_load"],
        "ambient_fixture_type_in_catalogue": not out["bad_ambient_fixture_type"],
        "bad_ambient_fixture_type": out["bad_ambient_fixture_type"],
        "ambient_fixture_use_valid": not out["ambient_fixture_wrong_use"],
        "ambient_fixture_wrong_use": out["ambient_fixture_wrong_use"],
        "ambient_lumens_match_catalogue": not out["bad_ambient_lumens"],
        "bad_ambient_lumens": out["bad_ambient_lumens"],
        "ambient_watts_match_catalogue": not out["bad_ambient_watts"],
        "bad_ambient_watts": out["bad_ambient_watts"],
        "ambient_count_meets_minimum": not out["ambient_count_too_low"],
        "ambient_count_too_low": out["ambient_count_too_low"],
        "ambient_lux_design_meets_target": not out["ambient_lux_below_target"],
        "ambient_lux_below_target": out["ambient_lux_below_target"],
        "ambient_spacing_within_layout_rule": not out["ambient_sh_above_max"],
        "ambient_sh_above_max": out["ambient_sh_above_max"],
        "perimeter_offset_matches_rule": not out["bad_perimeter_offset"],
        "bad_perimeter_offset": out["bad_perimeter_offset"],
        "task_recipe_zones_covered": not out["task_zone_missing"],
        "task_zone_missing": out["task_zone_missing"],
        "task_fixture_keys_in_catalogue": not out["bad_task_fixture_key"],
        "bad_task_fixture_key": out["bad_task_fixture_key"],
        "task_lumens_match_catalogue": not out["bad_task_lumens"],
        "bad_task_lumens": out["bad_task_lumens"],
        "task_watts_match_catalogue": not out["bad_task_watts"],
        "bad_task_watts": out["bad_task_watts"],
        "task_total_lumens_consistent": not out["bad_task_total_lumens"],
        "bad_task_total_lumens": out["bad_task_total_lumens"],
        "task_total_meets_target": not out["task_total_below_target"],
        "task_total_below_target": out["task_total_below_target"],
        "fixture_layout_ratios_valid": not out["bad_layout_ratios"],
        "bad_layout_ratios": out["bad_layout_ratios"],
        "fixture_layout_mount_matches_catalogue": not out["bad_layout_mount"],
        "bad_layout_mount": out["bad_layout_mount"],
        "fixture_layout_present": not out["fixture_layout_empty"],
        "fixture_layout_empty": out["fixture_layout_empty"],
        "outlet_types_in_catalogue": not out["bad_outlet_types"],
        "bad_outlet_types": out["bad_outlet_types"],
        "outlet_ratings_match_catalogue": not out["bad_outlet_rating"],
        "bad_outlet_rating": out["bad_outlet_rating"],
        "outlet_phases_match_catalogue": not out["bad_outlet_phase"],
        "bad_outlet_phase": out["bad_outlet_phase"],
        "general_outlets_meet_minimum": not out["general_outlets_below_min"],
        "general_outlets_below_min": out["general_outlets_below_min"],
        "total_connected_load_kw_consistent": not out["bad_total_connected_load_kw"],
        "bad_total_connected_load_kw": out["bad_total_connected_load_kw"],
        "panel_phase_consistent_with_load": not out["panel_phase_inconsistent_with_load"],
        "panel_phase_inconsistent_with_load": out["panel_phase_inconsistent_with_load"],
        "lighting_circuits_meet_minimum": not out["lighting_circuits_below_min"],
        "lighting_circuits_below_min": out["lighting_circuits_below_min"],
        "panel_spare_meets_20pct": not out["panel_spare_below_20"],
        "panel_spare_below_20": out["panel_spare_below_20"],
        "panel_phase_valid": not out["bad_panel_phase"],
        "bad_panel_phase": out["bad_panel_phase"],
        "dedicated_loads_in_catalogue": not out["bad_dedicated_load"],
        "bad_dedicated_load": out["bad_dedicated_load"],
        # Plumbing
        "plumbing_fixtures_present_when_declared": not out["plumbing_missing_fixtures"],
        "plumbing_missing_fixtures": out["plumbing_missing_fixtures"],
        "fixture_types_valid": not out["bad_fixture_types"],
        "bad_fixture_types": out["bad_fixture_types"],
        "dfu_values_match_brd": not out["bad_dfu_values"],
        "bad_dfu_values": out["bad_dfu_values"],
        "wsfu_values_match_brd": not out["bad_wsfu_values"],
        "bad_wsfu_values": out["bad_wsfu_values"],
        "total_dfu_matches_sum": not out["bad_total_dfu"],
        "bad_total_dfu": out["bad_total_dfu"],
        "total_wsfu_matches_sum": not out["bad_total_wsfu"],
        "bad_total_wsfu": out["bad_total_wsfu"],
        "demand_gpm_matches_hunters_curve": not out["bad_demand_gpm"],
        "bad_demand_gpm": out["bad_demand_gpm"],
        "demand_lpm_consistent_with_gpm": not out["bad_demand_lpm"],
        "bad_demand_lpm": out["bad_demand_lpm"],
        "supply_main_pipe_size_matches_table": not out["bad_supply_main_pipe"],
        "bad_supply_main_pipe": out["bad_supply_main_pipe"],
        "supply_curve_in_scope": not out["bad_supply_curve"],
        "bad_supply_curve": out["bad_supply_curve"],
        "main_drain_size_matches_table": not out["bad_main_drain_size"],
        "bad_main_drain_size": out["bad_main_drain_size"],
        "slope_in_brd_options": not out["bad_slope"],
        "bad_slope": out["bad_slope"],
        "slope_imperial_consistent": not out["bad_slope_imperial"],
        "bad_slope_imperial": out["bad_slope_imperial"],
        "every_fixture_has_trap": not out["trap_missing_for_fixture"],
        "trap_missing_for_fixture": out["trap_missing_for_fixture"],
        "trap_sizes_match_catalogue": not out["bad_trap_sizes"],
        "bad_trap_sizes": out["bad_trap_sizes"],
        "trap_types_match_catalogue": not out["bad_trap_types"],
        "bad_trap_types": out["bad_trap_types"],
        "trap_seal_meets_50mm": not out["bad_trap_seal"],
        "bad_trap_seal": out["bad_trap_seal"],
        "no_s_traps_specified": not out["s_trap_specified"],
        "s_trap_specified": out["s_trap_specified"],
        "vent_stack_size_matches_table": not out["bad_vent_stack_size"],
        "bad_vent_stack_size": out["bad_vent_stack_size"],
        "vent_terminal_meets_300mm": not out["vent_terminal_too_low"],
        "vent_terminal_too_low": out["vent_terminal_too_low"],
        "vent_types_in_scope": not out["bad_vent_types"],
        "bad_vent_types": out["bad_vent_types"],
        # Cost
        "currency_is_inr": not out["bad_currency"],
        "bad_currency": out["bad_currency"],
        "city_price_index_matches": not out["bad_city_index"],
        "bad_city_index": out["bad_city_index"],
        "all_cost_systems_present": not out["missing_cost_system"],
        "missing_cost_system": out["missing_cost_system"],
        "cost_system_keys_match_picks": not out["bad_cost_system_key"],
        "bad_cost_system_key": out["bad_cost_system_key"],
        "cost_rate_low_matches_brd": not out["bad_cost_rate_low"],
        "bad_cost_rate_low": out["bad_cost_rate_low"],
        "cost_rate_high_matches_brd": not out["bad_cost_rate_high"],
        "bad_cost_rate_high": out["bad_cost_rate_high"],
        "cost_totals_match_rate_x_area_x_index": not out["bad_cost_total"],
        "bad_cost_total": out["bad_cost_total"],
        "grand_total_matches_sum": not out["bad_grand_total"],
        "bad_grand_total": out["bad_grand_total"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class MEPSpecError(RuntimeError):
    """Raised when the LLM MEP-spec stage cannot produce a grounded sheet."""


async def generate_mep_spec(req: MEPSpecRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise MEPSpecError(
            "OpenAI API key is not configured. The MEP-spec stage requires "
            "a live LLM call; no static fallback is served."
        )

    use = _normalise_use(req.room_use_type)
    if use not in mep_kb.AIR_CHANGES_PER_HOUR:
        raise MEPSpecError(
            f"Unknown room_use_type '{req.room_use_type}'. "
            f"Pick one of: {', '.join(sorted(mep_kb.AIR_CHANGES_PER_HOUR.keys()))}."
        )

    bad_fixtures = [
        f for f in (req.fixtures or [])
        if _normalise_use(f) not in mep_kb.DFU_PER_FIXTURE
    ]
    if bad_fixtures:
        raise MEPSpecError(
            f"Unknown plumbing fixture(s): {', '.join(bad_fixtures)}. "
            f"Pick from: {', '.join(sorted(mep_kb.DFU_PER_FIXTURE.keys()))}."
        )

    knowledge = build_mep_spec_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": MEP_SPEC_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": MEP_SPEC_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for MEP spec")
        raise MEPSpecError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MEPSpecError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "mep_spec",
        "name": "MEP Specification",
        "model": settings.openai_model,
        "room_use_type": use,
        "city": req.city or None,
        "knowledge": knowledge,
        "mep_spec": spec,
        "validation": validation,
    }
