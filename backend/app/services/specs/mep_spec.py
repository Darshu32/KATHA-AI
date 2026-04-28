"""MEP specification builder (BRD Layer 3D).

Deterministic spec block consumed by the export pipeline. Mirrors the
LLM-grounded mep_spec_service.py output shape but is computed directly
from the design graph — used when the bundle exporter does not call
the live LLM stage.
"""

from __future__ import annotations

from app.knowledge import mep


def build(graph: dict) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_type = (room.get("type") or "living_room").lower()
    length = float(dims.get("length") or 0)
    width = float(dims.get("width") or 0)
    height = float(dims.get("height") or 0)
    area = length * width if length and width else 0
    volume = area * height if height else 0

    hvac_calc = mep.hvac_cfm(volume, room_type) if volume else {}
    cooling_use = _cooling_use_for(room_type)
    cooling_calc = mep.cooling_tr(area, cooling_use) if area else {}
    tonnage = cooling_calc.get("tonnage") or 0
    equipment = mep.equipment_capacity(tonnage) if tonnage else {}
    equipment_pick = mep.equipment_shortlist(tonnage) if tonnage else {}
    cfm = hvac_calc.get("cfm_total") or 0
    duct_round = mep.duct_round_diameter(cfm) if cfm else {}
    duct_rect = (
        mep.duct_rectangular_for_cfm(cfm, velocity_m_s=5.0, aspect_ratio=2.0)
        if cfm else {}
    )
    supply_pick = (
        mep.register_count(cfm, register_key="supply_6x10") if cfm else {}
    )
    return_pick = (
        mep.register_count(cfm * 0.9, register_key="return_grille_24x24")
        if cfm else {}
    )

    power_use = _power_use_for(room_type)
    lighting = mep.lighting_circuits(area, power_use) if area else {}
    ambient_lux = mep.LUX_LEVELS.get(f"{room_type}_general", 200)
    ambient_pick = (
        mep.ambient_fixture_count(area, ambient_lux, fixture_key="led_downlight_18w")
        if area else {}
    )
    perimeter = 2 * (length + width)
    outlet_pick = mep.outlet_estimate(room_type, perimeter) if perimeter else {}
    task_recipe = mep.TASK_LIGHTING_RECIPE.get(room_type) or []
    task_lighting = []
    for r in task_recipe:
        cat = mep.FIXTURE_CATALOGUE.get(r["fixture_key"]) or {}
        cnt = int(r.get("count_default") or 1)
        task_lighting.append({
            "zone": r["zone"],
            "fixture_key": r["fixture_key"],
            "lumens_per_fixture": cat.get("lumens"),
            "watts_per_fixture": cat.get("watts"),
            "count": cnt,
            "total_lumens": cnt * (cat.get("lumens") or 0),
            "target_lumens": r.get("target_lumens"),
        })

    fixtures = _plumbing_fixtures_from_graph(graph)
    fixture_types = [f["type"] for f in fixtures]
    total_dfu = sum(f["dfu"] for f in fixtures) if fixtures else 0
    pipe = mep.pipe_size_for_dfu(total_dfu) if total_dfu else {}
    supply_summary = mep.fixture_water_supply_summary(fixture_types) if fixtures else {}
    vent_pick = mep.vent_size_for_dfu(total_dfu, developed_length_m=15.0) if total_dfu else {}
    traps = [
        {
            "fixture_type": ft,
            **(mep.TRAP_SIZE_MM_PER_FIXTURE.get(ft) or {}),
            "developed_length_m": 1.0,
        }
        for ft in fixture_types
    ]

    hvac_system = _hvac_system_for(room_type, area)
    electrical_system = _electrical_system_for(room_type)
    plumbing_system = _plumbing_system_for(room_type)
    cost_blocks = {
        "hvac": mep.system_cost_estimate(hvac_system, area) if area else {},
        "electrical": mep.system_cost_estimate(electrical_system, area) if area else {},
        "plumbing": mep.system_cost_estimate(plumbing_system, area) if area else {},
    }
    grand_low = sum((b.get("total_inr") or {}).get("low") or 0 for b in cost_blocks.values())
    grand_high = sum((b.get("total_inr") or {}).get("high") or 0 for b in cost_blocks.values())

    return {
        "geometry": {
            "length_m": length, "width_m": width, "height_m": height,
            "area_m2": round(area, 2), "volume_m3": round(volume, 2),
        },
        "hvac": {
            "room_volume_m3": round(volume, 2),
            "ach_target": hvac_calc.get("ach"),
            "cfm_fresh_air": cfm or None,
            "cooling": {
                "tonnage": tonnage or None,
                "btu_per_hr": equipment.get("btu_per_hr"),
                "kw_thermal": equipment.get("kw_thermal"),
            },
            "equipment": {
                "selected_tr": equipment_pick.get("selected_tr"),
                "type": equipment_pick.get("type"),
                "unit_count": 1 if equipment_pick.get("selected_tr") else 0,
            },
            "ductwork": {
                "round_diameter_mm": duct_round.get("diameter_mm"),
                "rectangular_mm": {
                    "width": duct_rect.get("width_mm"),
                    "height": duct_rect.get("height_mm"),
                    "velocity_m_s": duct_rect.get("velocity_m_s"),
                },
                "velocity_band_main_supply_m_s": list(mep.DUCT_VELOCITY_M_S["main_supply"]),
            },
            "supply_registers": {
                "type": supply_pick.get("register_type"),
                "count": supply_pick.get("count"),
                "cfm_each": supply_pick.get("cfm_per_register"),
                "spacing_rule": supply_pick.get("spacing_rule"),
            } if supply_pick else {},
            "return_registers": {
                "type": return_pick.get("register_type"),
                "count": return_pick.get("count"),
                "cfm_each": return_pick.get("cfm_per_register"),
            } if return_pick else {},
        },
        "electrical": {
            "ambient_lux_target": ambient_lux,
            "task_lux_target": (
                mep.LUX_LEVELS.get(f"{room_type}_task")
                or mep.LUX_LEVELS.get(f"{room_type}_general", ambient_lux)
            ),
            "power_density_w_per_m2": lighting.get("density_w_m2"),
            "total_lighting_load_w": lighting.get("total_load_w"),
            "ambient_fixtures": {
                "type": ambient_pick.get("fixture_key"),
                "lumens_per_fixture": ambient_pick.get("lumens_per_fixture"),
                "watts_per_fixture": ambient_pick.get("watts_per_fixture"),
                "count": ambient_pick.get("count"),
                "total_watts": ambient_pick.get("total_watts"),
                "lux_design": ambient_pick.get("lux_design"),
                "perimeter_offset_m": mep.LIGHTING_LAYOUT_RULES["perimeter_offset_m"],
            } if ambient_pick else {},
            "task_lighting": task_lighting,
            "lighting_circuits": lighting.get("lighting_circuits"),
            "outlets": {
                "general_outlet_count": outlet_pick.get("general_outlets"),
                "task_zones": outlet_pick.get("task_zones"),
                "perimeter_m": outlet_pick.get("perimeter_m"),
            } if outlet_pick else {},
            "outlet_recommendation": (
                "1 duplex outlet every 3–4 linear m of wall; "
                "dedicated 16 A points for AC and kitchen appliances; "
                "20 A point for geyser; USB-A/C combos at task zones."
            ),
        },
        "plumbing": {
            "fixtures": fixtures,
            "total_dfu": total_dfu,
            "total_wsfu": supply_summary.get("wsfu_total"),
            "water_supply": {
                "demand_gpm": supply_summary.get("demand_gpm"),
                "demand_lpm": supply_summary.get("demand_lpm"),
                "supply_main_pipe_size_mm": supply_summary.get("supply_main_pipe_size_mm"),
                "curve": "hunter_flush_tank",
            } if supply_summary else {},
            "main_drain_size_mm": pipe.get("pipe_size_mm"),
            "slope_per_metre": mep.SLOPE_REQUIREMENT["horizontal_drain_preferred"]["ratio"],
            "slope_imperial": mep.SLOPE_REQUIREMENT["horizontal_drain_preferred"]["imperial"],
            "traps": traps,
            "vent_stack_size_mm": vent_pick.get("vent_size_mm"),
            "vent_developed_length_m": vent_pick.get("developed_length_m"),
            "vent_terminal_height_above_roof_mm": 300,
            "water_demand_lpd": (
                mep.WATER_DEMAND_LPM.get(f"{room_type}_per_person_per_day")
                or mep.WATER_DEMAND_LPM["residential_per_person_per_day"]
            ),
        },
        "cost": {
            "currency": "INR",
            "systems": cost_blocks,
            "grand_total_inr": {"low": grand_low, "high": grand_high},
        },
    }


# ── helpers ─────────────────────────────────────────────────────────────────


def _cooling_use_for(use: str) -> str:
    use = (use or "").lower()
    if use in mep.COOLING_LOAD_TR_PER_M2:
        return use
    if use in {"bedroom", "living_room", "kitchen", "bathroom", "hotel_room"}:
        return "residential"
    if use in {"office_general", "classroom"}:
        return "office_general"
    if use == "conference_room":
        return "conference"
    if use in {"restaurant_dining", "restaurant_kitchen"}:
        return "restaurant"
    if use == "retail":
        return "retail"
    return "office_general"


def _power_use_for(use: str) -> str:
    use = (use or "").lower()
    if use in mep.POWER_DENSITY_W_PER_M2:
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
    use = (use or "").lower()
    if use in {"bedroom", "living_room", "kitchen", "bathroom", "hotel_room"}:
        return "hvac_split_residential"
    if area_m2 >= 2000:
        return "hvac_chilled_water_large"
    return "hvac_vrf_commercial"


def _electrical_system_for(use: str) -> str:
    use = (use or "").lower()
    return "electrical_residential" if use in {
        "bedroom", "living_room", "kitchen", "bathroom", "hotel_room"
    } else "electrical_commercial"


def _plumbing_system_for(use: str) -> str:
    use = (use or "").lower()
    return "plumbing_residential" if use in {
        "bedroom", "living_room", "kitchen", "bathroom", "hotel_room"
    } else "plumbing_commercial"


def _plumbing_fixtures_from_graph(graph: dict) -> list[dict]:
    fixtures: list[dict] = []
    type_to_fixture = {
        "water_closet": "water_closet", "wc": "water_closet", "toilet": "water_closet",
        "urinal": "urinal",
        "wash_basin": "wash_basin", "basin": "wash_basin", "sink": "wash_basin",
        "kitchen_sink": "kitchen_sink",
        "shower": "shower", "bathtub": "bathtub", "tub": "bathtub",
        "floor_drain": "floor_drain",
        "washing_machine": "washing_machine",
    }
    for obj in graph.get("objects", []):
        t = (obj.get("type") or "").lower()
        key = type_to_fixture.get(t)
        if not key:
            continue
        dfu = mep.DFU_PER_FIXTURE.get(key, 1)
        fixtures.append({"id": obj.get("id"), "type": key, "dfu": dfu})
    return fixtures
