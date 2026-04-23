"""International Building Code (IBC) reference — for non-India projects.

Companion to `codes.py` (which covers NBC India + ECBC + accessibility).
Used when the brief's regulatory context is outside India, or when the
client explicitly requests international benchmarking.

Values are drawn from the 2021 IBC edition where practical and kept at
the summary level — not a legal substitute. Units converted from imperial
to SI where possible for consistency with the rest of the knowledge base.
"""

from __future__ import annotations

# ── IBC Chapter 3 — Occupancy classifications (condensed) ────────────────────
OCCUPANCY_GROUPS: dict[str, dict] = {
    "A": {"name": "Assembly", "examples": "theatres, restaurants > 49 occupants"},
    "B": {"name": "Business", "examples": "offices, professional services"},
    "E": {"name": "Educational", "examples": "schools through 12th grade"},
    "F": {"name": "Factory / Industrial", "examples": "manufacturing"},
    "H": {"name": "High Hazard", "examples": "chemical, combustible storage"},
    "I": {"name": "Institutional", "examples": "hospitals, prisons"},
    "M": {"name": "Mercantile", "examples": "retail, markets"},
    "R": {"name": "Residential", "examples": "hotels, apartments, SFR"},
    "S": {"name": "Storage", "examples": "warehouses"},
    "U": {"name": "Utility", "examples": "accessory structures"},
}

# ── IBC Chapter 5 — Construction types (very condensed height/area) ──────────
CONSTRUCTION_TYPES: dict[str, dict] = {
    "I-A": {"fire_resistance_hr": 3, "area_limit": "unlimited (non-sprinklered)"},
    "I-B": {"fire_resistance_hr": 2, "area_limit": "unlimited"},
    "II-A": {"fire_resistance_hr": 1, "area_limit": "varies"},
    "II-B": {"fire_resistance_hr": 0, "area_limit": "varies"},
    "III-A": {"fire_resistance_hr": 1, "area_limit": "varies", "notes": "non-combustible ext."},
    "III-B": {"fire_resistance_hr": 0, "area_limit": "varies", "notes": "non-combustible ext."},
    "IV": {"fire_resistance_hr": 2, "area_limit": "varies", "notes": "heavy timber / mass timber"},
    "V-A": {"fire_resistance_hr": 1, "area_limit": "limited"},
    "V-B": {"fire_resistance_hr": 0, "area_limit": "most restricted"},
}

# ── IBC Chapter 10 — Means of Egress (metric-converted) ──────────────────────
EGRESS: dict[str, dict] = {
    "doorway": {
        "min_clear_width_mm": 815,     # 32" clear
        "min_height_mm": 2030,          # 80"
    },
    "corridor": {
        "min_width_mm_occupancy_lt_50": 915,      # 36"
        "min_width_mm_occupancy_ge_50": 1120,     # 44"
        "min_width_mm_healthcare": 2440,          # 96"
    },
    "exit_width_per_occupant_mm": {
        "stair": 7.6,     # 0.3" / occupant
        "other": 5.1,     # 0.2" / occupant
    },
    "max_travel_distance_m": {
        "A_sprinklered": 76,
        "A_nonsprinklered": 61,
        "B_sprinklered": 91,
        "B_nonsprinklered": 61,
        "R_sprinklered": 76,
        "R_nonsprinklered": 38,
    },
    "common_path_of_travel_max_m": {
        "B_sprinklered": 30.5,
        "R_sprinklered": 38,
    },
    "dead_end_corridor_max_m": 15.2,  # 50 ft (sprinklered Group B/R)
}

# ── IBC Chapter 11 — Accessibility (cross-refs ANSI A117.1 / ADA) ────────────
ACCESSIBILITY: dict[str, dict] = {
    "ramp": {
        "max_slope_ratio": 1 / 12,
        "max_rise_per_run_mm": 762,          # 30" max rise before landing
        "landing_min_length_mm": 1525,        # 60"
        "min_width_mm": 915,
    },
    "door": {
        "min_clear_width_mm": 815,
        "max_opening_force_n": 22,            # interior
        "threshold_max_mm": 13,               # 1/2"
    },
    "reach_range_mm": {
        "forward_unobstructed_high": 1220,
        "side_unobstructed_high": 1372,
        "low": 380,
    },
    "toilet_room": {
        "clear_floor_circle_diameter_mm": 1525,
        "wheelchair_wc_stall_mm": "1525 x 1675",
        "grab_bar_height_mm": (840, 915),
    },
    "parking": {
        "accessible_spaces_per_25": 1,
        "van_accessible_per_6_accessible": 1,
        "accessible_stall_width_mm": 2440,
        "aisle_width_mm": 1525,
    },
}

# ── IBC Chapter 16 — Structural loads (condensed, ASCE 7 alignment) ──────────
LIVE_LOADS_KN_PER_M2: dict[str, float] = {
    "residential_dwelling": 1.92,       # 40 psf
    "residential_sleeping": 1.44,       # 30 psf
    "office_general": 2.40,              # 50 psf
    "office_corridor_first_floor": 4.79, # 100 psf
    "assembly_fixed_seats": 2.87,        # 60 psf
    "assembly_movable_seats": 4.79,      # 100 psf
    "retail_first_floor": 4.79,          # 100 psf
    "retail_upper_floors": 3.59,         # 75 psf
    "warehouse_light": 5.99,             # 125 psf
    "warehouse_heavy": 11.97,            # 250 psf
}

# ── IBC Chapter 12 — Interior environment minima ─────────────────────────────
INTERIOR_ENVIRONMENT: dict[str, dict] = {
    "ceiling_height": {
        "habitable_min_mm": 2130,         # 7'-0"
        "bathroom_min_mm": 2030,           # 6'-8" at fixture
    },
    "room_dimensions": {
        "habitable_min_area_m2": 6.5,     # ~70 sqft
        "habitable_min_dim_m": 2.13,
    },
    "natural_light_glazing_percent_floor": 8.0,
    "natural_ventilation_openable_percent_floor": 4.0,
}

# ── IECC (International Energy Conservation Code) — envelope targets ─────────
ENERGY_ENVELOPE_U_VALUES_W_M2K: dict[str, dict] = {
    "climate_zone_1_tropical": {"wall": 0.45, "roof": 0.27},
    "climate_zone_2_hot": {"wall": 0.40, "roof": 0.23},
    "climate_zone_3_warm": {"wall": 0.34, "roof": 0.18},
    "climate_zone_4_mixed": {"wall": 0.28, "roof": 0.15},
    "climate_zone_5_cool": {"wall": 0.24, "roof": 0.15},
    "climate_zone_6_cold": {"wall": 0.22, "roof": 0.14},
    "climate_zone_7_very_cold": {"wall": 0.17, "roof": 0.12},
}


def describe_for_prompt() -> str:
    """Condensed IBC reference block for LLM grounding."""
    e = EGRESS
    a = ACCESSIBILITY
    ie = INTERIOR_ENVIRONMENT
    return (
        "[IBC 2021 summary]\n"
        f"- Egress: door clear {e['doorway']['min_clear_width_mm']}mm, "
        f"corridor ≥50occ {e['corridor']['min_width_mm_occupancy_ge_50']}mm, "
        f"dead-end max {e['dead_end_corridor_max_m']}m. "
        f"Travel B-sprinklered {e['max_travel_distance_m']['B_sprinklered']}m, "
        f"R-sprinklered {e['max_travel_distance_m']['R_sprinklered']}m.\n"
        f"- Accessibility: ramp 1:12, door clear {a['door']['min_clear_width_mm']}mm, "
        f"toilet circle Ø{a['toilet_room']['clear_floor_circle_diameter_mm']}mm.\n"
        f"- Interior: habitable ceiling ≥{ie['ceiling_height']['habitable_min_mm']}mm, "
        f"glazing ≥{ie['natural_light_glazing_percent_floor']}% floor, "
        f"openable ≥{ie['natural_ventilation_openable_percent_floor']}% floor."
    )
