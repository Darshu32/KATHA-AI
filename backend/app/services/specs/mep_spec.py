"""MEP specification builder (BRD Layer 3D).

Runs HVAC / electrical / plumbing calculators against the room and
produces a structured spec block the exporters can render.
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

    hvac = mep.hvac_cfm(volume, room_type) if volume else {"error": "volume missing"}
    cooling = mep.cooling_tr(area, room_type) if area else {"error": "area missing"}
    lighting = mep.lighting_circuits(area, "residential") if area else {}

    fixtures = _plumbing_fixtures_from_graph(graph)
    total_dfu = sum(f["dfu"] for f in fixtures) if fixtures else 0
    pipe = mep.pipe_size_for_dfu(total_dfu) if total_dfu else {}

    return {
        "hvac": {
            "room_volume_m3": round(volume, 2),
            "ach_target": hvac.get("ach"),
            "cfm_fresh_air": hvac.get("cfm_total"),
            "cooling_tr": cooling.get("tonnage"),
            "duct_velocity_m_s": mep.DUCT_VELOCITY_M_S.get("main_supply"),
        },
        "electrical": {
            "ambient_lux_target": mep.LUX_LEVELS.get(f"{room_type}_general", 200),
            "task_lux_target": mep.LUX_LEVELS.get(f"{room_type}_task") or mep.LUX_LEVELS.get(f"{room_type}_general"),
            "power_density_w_per_m2": lighting.get("density_w_m2"),
            "total_lighting_load_w": lighting.get("total_load_w"),
            "lighting_circuits": lighting.get("lighting_circuits"),
            "outlet_recommendation": "1 duplex outlet every 3–4 linear m of wall; dedicated circuits for AC and kitchen appliances.",
        },
        "plumbing": {
            "fixtures": fixtures,
            "total_dfu": total_dfu,
            "main_drain_size_mm": pipe.get("pipe_size_mm"),
            "slope_per_metre": mep.SLOPE_PER_METRE["horizontal_drain_preferred"],
            "water_demand_lpd": mep.WATER_DEMAND_LPM.get(f"{room_type}_per_person_per_day")
                                or mep.WATER_DEMAND_LPM["residential_per_person_per_day"],
        },
    }


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
