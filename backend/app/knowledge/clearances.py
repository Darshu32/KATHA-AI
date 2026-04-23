"""Clearances, circulation, and egress dimensions.

Values in millimetres. Sourced from BRD Layer 1B, NBC India Part 4,
and IBC Chapter 10.
"""

from __future__ import annotations

DOORS: dict[str, dict] = {
    "main_entry": {"width_mm": (1000, 1200), "height_mm": (2100, 2400)},  # BRD: 1000mm
    "interior": {"width_mm": (800, 900), "height_mm": (2000, 2100)},      # BRD: 800-900
    "bathroom": {"width_mm": (700, 800), "height_mm": (2000, 2100)},
    "emergency_egress": {"width_mm": (900, 1200), "height_mm": (2100, 2400)},
    "sliding": {"width_mm": (1200, 2400), "height_mm": (2100, 2400)},
}

WINDOWS: dict[str, dict] = {
    "bedroom_standard": {"width_mm": (1200, 1800), "sill_height_mm": (900, 1050)},
    "living_picture": {"width_mm": (1500, 3000), "sill_height_mm": (400, 600)},
    "bathroom_vent": {"width_mm": (600, 900), "sill_height_mm": (1500, 1800)},
    "kitchen": {"width_mm": (1000, 1500), "sill_height_mm": (900, 1050)},
}

CORRIDORS: dict[str, dict] = {
    "residential": {"min_width_mm": 800, "preferred_mm": 1000},          # BRD
    "commercial": {"min_width_mm": 1200, "preferred_mm": 1500},           # BRD
    "hospital": {"min_width_mm": 2400},
    "accessibility_universal": {"min_width_mm": 1500},                    # wheelchair passing
}

STAIRS: dict[str, dict] = {
    "residential": {
        "rise_mm": (150, 200),      # BRD example: 180
        "tread_mm": (250, 300),     # BRD example: 280
        "min_width_mm": 900,
        "headroom_mm": 2100,
        "max_rise_run_rule": "2*rise + tread ~ 600-640mm",
    },
    "commercial": {
        "rise_mm": (150, 180),
        "tread_mm": (280, 320),
        "min_width_mm": 1200,
        "headroom_mm": 2100,
    },
    "fire_escape": {
        "rise_mm": (150, 180),
        "tread_mm": (280, 300),
        "min_width_mm": 1200,
        "handrails": "both sides mandatory",
    },
}

RAMPS: dict[str, dict] = {
    "accessibility": {
        "max_slope_ratio": 1 / 12,   # 1:12 universal
        "min_width_mm": 1200,
        "landing_every_m": 9.0,
        "handrail_height_mm": (865, 965),
    },
    "loading": {
        "max_slope_ratio": 1 / 8,
    },
}

# Furniture circulation clearances (mm).
CIRCULATION: dict[str, int] = {
    "around_bed": 600,
    "around_dining_table": 750,
    "in_front_of_sofa": 400,
    "kitchen_walkway_single": 900,
    "kitchen_walkway_double": 1200,
    "desk_pullout": 900,
    "wardrobe_opening": 900,
}

EGRESS: dict[str, dict] = {
    "max_travel_distance_residential_m": 30,
    "max_travel_distance_office_unsprinklered_m": 45,
    "max_travel_distance_office_sprinklered_m": 60,
    "min_exit_count_over_50_occupants": 2,
    "dead_end_corridor_max_m": 6,
}


def check_door(category: str, width_mm: float) -> dict:
    spec = DOORS.get(category)
    if not spec:
        return {"status": "unknown", "message": f"No standard for door '{category}'."}
    lo, hi = spec["width_mm"]
    if width_mm < lo:
        return {"status": "warn_low", "message": f"{category} door width {width_mm}mm below {lo}mm."}
    if width_mm > hi * 1.5:
        return {"status": "warn_high", "message": f"{category} door width {width_mm}mm unusually large."}
    return {"status": "ok", "message": f"Within {lo}-{hi}mm."}


def check_corridor(segment: str, width_mm: float) -> dict:
    spec = CORRIDORS.get(segment)
    if not spec:
        return {"status": "unknown", "message": f"No standard for corridor '{segment}'."}
    min_w = spec["min_width_mm"]
    if width_mm < min_w:
        return {"status": "warn_low", "message": f"{segment} corridor {width_mm}mm below minimum {min_w}mm."}
    return {"status": "ok", "message": f"Meets >= {min_w}mm."}
