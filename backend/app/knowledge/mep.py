"""MEP sizing rules — HVAC, electrical, plumbing.

Per BRD Layer 1B. References: ASHRAE 62.1, NEC / IS 732, NBC Part 9.
"""

from __future__ import annotations

# ── HVAC ─────────────────────────────────────────────────────────────────────
# Air changes per hour by use (ASHRAE 62.1 / NBC).
AIR_CHANGES_PER_HOUR: dict[str, float] = {
    "bedroom": 2.0,
    "living_room": 3.0,
    "kitchen": 10.0,         # exhaust driven
    "bathroom": 8.0,
    "office_general": 4.0,
    "conference_room": 8.0,
    "restaurant_dining": 10.0,
    "restaurant_kitchen": 15.0,
    "retail": 6.0,
    "hotel_room": 4.0,
    "gym": 10.0,
    "classroom": 6.0,
}

# CFM per person (fresh air / ventilation).
CFM_PER_PERSON: dict[str, float] = {
    "office": 15,
    "conference": 20,
    "classroom": 15,
    "restaurant": 20,
    "retail": 15,
    "residential": 10,
    "hospital_patient": 25,
    "gym": 20,
}

# Cooling load rule-of-thumb (TR per m^2, tropical India).
COOLING_LOAD_TR_PER_M2: dict[str, float] = {
    "residential": 1 / 13,     # ~ 1 TR / 13 m^2 (~140 sqft)
    "office_general": 1 / 9,
    "restaurant": 1 / 7,
    "retail": 1 / 10,
    "conference": 1 / 7,
    "server_room": 1 / 3,
}

# Duct sizing velocity targets (m/s).
DUCT_VELOCITY_M_S: dict[str, tuple[float, float]] = {
    "main_supply": (6.0, 9.0),
    "branch": (3.0, 5.0),
    "return": (4.0, 6.0),
    "residential": (3.0, 5.0),
}


def hvac_cfm(room_volume_m3: float, use_type: str) -> dict:
    """Total fresh-air CFM required for a room."""
    ach = AIR_CHANGES_PER_HOUR.get(use_type)
    if not ach:
        return {"error": f"Unknown use_type '{use_type}'"}
    cfm = (room_volume_m3 * 35.31 * ach) / 60.0  # m^3 -> ft^3, divide by 60 min
    return {"ach": ach, "cfm_total": round(cfm, 1), "use_type": use_type}


def cooling_tr(area_m2: float, use_type: str) -> dict:
    factor = COOLING_LOAD_TR_PER_M2.get(use_type)
    if not factor:
        return {"error": f"No cooling factor for '{use_type}'"}
    tr = area_m2 * factor
    return {"tonnage": round(tr, 2), "use_type": use_type}


# ── Electrical ───────────────────────────────────────────────────────────────
LUX_LEVELS: dict[str, int] = {
    "bedroom_general": 100,
    "bedroom_reading": 300,
    "living_room_general": 150,
    "living_room_task": 400,
    "kitchen_general": 300,
    "kitchen_counter": 500,
    "bathroom": 200,
    "office_general": 500,
    "office_task": 750,
    "conference_room": 500,
    "corridor": 100,
    "staircase": 150,
    "restaurant_dining": 200,
    "retail_general": 500,
    "retail_display": 1000,
}

CIRCUIT_LOAD_W: dict[str, int] = {
    "lighting_circuit_max": 1500,
    "general_outlet_circuit_max": 2400,
    "kitchen_appliance_circuit_max": 3000,
    "ac_dedicated_1_5_ton": 2200,
    "geyser_dedicated": 3000,
    "oven_dedicated": 4000,
}

POWER_DENSITY_W_PER_M2: dict[str, int] = {
    "residential": 30,
    "office_general": 70,
    "office_high_tech": 120,
    "retail": 80,
    "restaurant": 100,
    "server_room": 800,
}


def lighting_circuits(area_m2: float, use: str = "residential") -> dict:
    density = POWER_DENSITY_W_PER_M2.get(use, 40)
    total_w = area_m2 * density
    n = max(1, int(total_w // CIRCUIT_LOAD_W["lighting_circuit_max"]) + 1)
    return {"total_load_w": int(total_w), "lighting_circuits": n, "density_w_m2": density}


# ── Plumbing ─────────────────────────────────────────────────────────────────
# Drainage Fixture Units (DFU) per fixture.
DFU_PER_FIXTURE: dict[str, int] = {
    "water_closet": 4,
    "urinal": 2,
    "wash_basin": 1,
    "kitchen_sink": 2,
    "shower": 2,
    "bathtub": 2,
    "floor_drain": 1,
    "washing_machine": 2,
}

# Trap / pipe sizing by DFU total.
PIPE_SIZE_MM_BY_DFU: list[tuple[int, int]] = [
    (3, 50),
    (6, 65),
    (24, 75),
    (84, 100),
    (256, 125),
    (600, 150),
]

SLOPE_PER_METRE: dict[str, float] = {
    "horizontal_drain_min": 0.01,    # 1% = 1:100
    "horizontal_drain_preferred": 0.02,
    "vent_horizontal": 0.01,
}

WATER_DEMAND_LPM: dict[str, tuple[int, int]] = {
    "residential_per_person_per_day": (135, 200),  # litres/day
    "hotel_per_guest_per_day": (180, 300),
    "office_per_person_per_day": (45, 70),
    "restaurant_per_seat_per_day": (65, 100),
}


def pipe_size_for_dfu(total_dfu: int) -> dict:
    for limit, size in PIPE_SIZE_MM_BY_DFU:
        if total_dfu <= limit:
            return {"total_dfu": total_dfu, "pipe_size_mm": size}
    return {"total_dfu": total_dfu, "pipe_size_mm": PIPE_SIZE_MM_BY_DFU[-1][1], "note": "exceeds table; size up"}


# ── System cost per m² (major MEP systems, indicative INR ranges) ────────────
# Baseline for Tier-1 Indian metros, mid-spec. Used by cost/estimation stage
# and surfaced in the architect brief for early budgeting.
SYSTEM_COST_INR_PER_M2: dict[str, dict] = {
    "hvac_split_residential": {
        "range": (1200, 2200),
        "notes": "Wall-mounted splits + ducting; excludes mains power",
    },
    "hvac_vrf_commercial": {
        "range": (3500, 6500),
        "notes": "VRF outdoor + indoor units, refrigerant piping, controls",
    },
    "hvac_chilled_water_large": {
        "range": (5500, 9000),
        "notes": "Chiller, AHUs, ducting, pumping; viable above ~2000 m²",
    },
    "electrical_residential": {
        "range": (900, 1600),
        "notes": "Wiring, distribution board, fixtures, points — mid-spec",
    },
    "electrical_commercial": {
        "range": (1800, 3200),
        "notes": "Higher power density, UPS rough-in, BMS-ready",
    },
    "plumbing_residential": {
        "range": (700, 1300),
        "notes": "CPVC supply + PVC/UPVC drainage; excludes fixtures",
    },
    "plumbing_commercial": {
        "range": (1400, 2400),
        "notes": "Stacked toilet cores, booster pumping, water treatment",
    },
    "fire_fighting_residential": {
        "range": (400, 800),
        "notes": "Sprinklers + wet-riser for high-rise; excluded for low-rise",
    },
    "fire_fighting_commercial": {
        "range": (900, 1600),
        "notes": "Sprinkler network, hydrants, alarm + detection",
    },
    "low_voltage_commercial": {
        "range": (600, 1400),
        "notes": "Data, access control, CCTV, PA, BMS",
    },
}


def system_cost_estimate(system_key: str, area_m2: float) -> dict:
    """Rough order-of-magnitude system cost for an area.

    Returned ranges are multiplied by the area; callers should apply a
    regional price index (see knowledge.regional_materials) on top.
    """
    spec = SYSTEM_COST_INR_PER_M2.get(system_key)
    if not spec:
        return {"error": f"No cost band for system '{system_key}'"}
    lo, hi = spec["range"]
    return {
        "system": system_key,
        "area_m2": area_m2,
        "rate_inr_m2": {"low": lo, "high": hi},
        "total_inr": {"low": round(lo * area_m2, 0), "high": round(hi * area_m2, 0)},
        "notes": spec["notes"],
    }
