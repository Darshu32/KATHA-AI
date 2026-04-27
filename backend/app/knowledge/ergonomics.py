"""Ergonomic dimension ranges for furniture.

All values in millimetres unless otherwise noted. Ranges are (min, max).
Sourced from BRD Layer 1C and Neufert.
"""

from __future__ import annotations

# Structure: each item exposes overall envelope + key ergonomic dims.
# BRD 1C — Chairs: seat 40–45 (std) / 35–40 (low), depth 45–50,
# backrest 75–90 from floor, arm 60–65 from floor, width 60–75.
CHAIRS: dict[str, dict] = {
    "dining_chair": {
        "seat_height_mm": (400, 450),       # BRD: 40–45 cm standard
        "seat_depth_mm": (450, 500),        # BRD: 45–50 cm
        "seat_width_mm": (430, 500),
        "backrest_height_mm": (750, 900),   # BRD: 75–90 cm from floor
        "arm_height_mm": (600, 650),        # BRD: 60–65 cm from floor (if armed)
        "overall_width_mm": (450, 550),
        "overall_depth_mm": (500, 580),
        "overall_height_mm": (800, 950),
    },
    "armchair": {
        "seat_height_mm": (400, 450),       # BRD: standard
        "seat_depth_mm": (450, 500),
        "seat_width_mm": (500, 650),
        "backrest_height_mm": (750, 900),
        "arm_height_mm": (600, 650),
        "overall_width_mm": (600, 750),     # BRD: 60–75 cm overall width
        "overall_depth_mm": (700, 900),
        "overall_height_mm": (800, 950),
    },
    "lounge_chair": {
        "seat_height_mm": (350, 400),       # BRD: 35–40 cm low seat
        "seat_depth_mm": (500, 600),
        "seat_width_mm": (500, 650),
        "backrest_height_mm": (750, 900),
        "arm_height_mm": (550, 650),
        "overall_width_mm": (700, 900),
        "overall_depth_mm": (800, 1000),
        "overall_height_mm": (750, 950),
    },
    "office_chair": {
        "seat_height_mm": (420, 520),       # adjustable
        "seat_depth_mm": (450, 500),        # BRD aligned
        "seat_width_mm": (450, 500),
        "backrest_height_mm": (800, 1200),
        "arm_height_mm": (620, 720),
        "overall_width_mm": (600, 720),
        "overall_depth_mm": (600, 720),
        "overall_height_mm": (900, 1300),
    },
}

# BRD 1C — Tables: dining 72–75 cm H × 90–120 cm W × 60 cm D min;
# coffee 40–50 cm H × 80–120 cm L; workspace 120–150 cm × 60 cm D.
TABLES: dict[str, dict] = {
    "dining_table": {
        "height_mm": (720, 750),        # BRD: 72–75 cm
        "width_mm": (900, 1200),        # BRD: 90–120 cm
        "depth_mm_min": 600,            # BRD: 60 cm depth minimum
        "depth_mm": (600, 1000),
        "area_per_seat_m2": (0.55, 0.75),
    },
    "coffee_table": {
        "height_mm": (400, 500),        # BRD: 40–50 cm
        "length_mm": (800, 1200),       # BRD: 80–120 cm
        "depth_mm": (500, 700),
    },
    "desk": {
        "height_mm": (720, 750),
        "length_mm": (1200, 1500),      # BRD: workspace 120–150 cm
        "depth_mm_min": 600,            # BRD: 60 cm depth minimum
        "depth_mm": (600, 800),
    },
    "console_table": {
        "height_mm": (750, 850),
        "length_mm": (900, 1500),
        "depth_mm": (300, 400),
    },
    "side_table": {
        "height_mm": (500, 650),
        "length_mm": (400, 600),
        "depth_mm": (400, 600),
    },
}

# BRD 1C — Beds: platform 45–50 cm, raised 55–60 cm;
# single 90×200, double 140×200, queen 150×200; under-bed storage 30–40 cm.
BEDS: dict[str, dict] = {
    "single": {
        "mattress_mm": (900, 2000),         # BRD: 90×200 cm
        "platform_height_mm": (450, 500),
        "raised_height_mm": (550, 600),
    },
    "double": {
        "mattress_mm": (1400, 2000),        # BRD: 140×200 cm
        "platform_height_mm": (450, 500),
        "raised_height_mm": (550, 600),
    },
    "queen": {
        "mattress_mm": (1500, 2000),        # BRD: 150×200 cm
        "platform_height_mm": (450, 500),
        "raised_height_mm": (550, 600),
    },
    "king": {
        "mattress_mm": (1800, 2000),
        "platform_height_mm": (450, 500),
        "raised_height_mm": (550, 600),
    },
}
BED_UNDER_STORAGE_MM = (300, 400)          # BRD: 30–40 cm

# BRD 1C — Storage: shelf depth 30 cm (books) / 45 cm (objects);
# cabinet height 180–200 cm standard; counter 85–90 cm; toe kick 10 cm min.
STORAGE: dict[str, dict] = {
    "bookshelf": {
        "shelf_depth_mm": (280, 320),           # BRD: 30 cm for books
        "shelf_pitch_mm": (280, 360),
        "overall_height_mm": (1800, 2000),      # BRD: 180–200 cm standard
    },
    "object_shelf": {
        "shelf_depth_mm": (420, 480),           # BRD: 45 cm for objects
        "shelf_pitch_mm": (350, 500),
        "overall_height_mm": (1800, 2000),
    },
    "display_shelf": {
        "shelf_depth_mm": (350, 500),
        "shelf_pitch_mm": (350, 500),
    },
    "cabinet": {
        "depth_mm": (400, 600),
        "overall_height_mm": (1800, 2000),      # BRD: 180–200 cm standard
        "notes": "Generic free-standing / tall cabinet envelope.",
    },
    "wardrobe": {
        "depth_mm": (580, 650),
        "hang_rail_height_mm": (1650, 1900),
        "overall_height_mm": (1800, 2400),
    },
    "kitchen_cabinet_base": {
        "depth_mm": (550, 600),
        "height_mm": (850, 900),                # BRD counter: 85–90 cm
        "toe_kick_height_mm": (100, 150),       # BRD: 10 cm minimum
        "toe_kick_depth_mm": (60, 80),
    },
    "kitchen_cabinet_wall": {
        "depth_mm": (300, 350),
        "bottom_from_counter_mm": (500, 600),
        "height_mm": (600, 900),
    },
    "counter": {
        "height_mm": (850, 900),                # BRD: 85–90 cm
        "depth_mm": (600, 650),
        "toe_kick_height_mm_min": 100,          # BRD: 10 cm minimum
    },
    "tv_unit": {
        "depth_mm": (350, 500),
        "height_mm": (400, 600),
    },
}


def check_range(category: str, item: str, dim: str, value_mm: float) -> dict:
    """Validate a single dimension against the ergonomic range."""
    tables = {"chair": CHAIRS, "table": TABLES, "bed": BEDS, "storage": STORAGE}
    table = tables.get(category.lower())
    if not table or item not in table:
        return {"status": "unknown", "message": f"No range for {category}/{item}."}
    spec = table[item]
    key = dim if dim in spec else f"{dim}_mm"
    if key not in spec:
        return {"status": "unknown", "message": f"No dim '{dim}' for {item}."}
    lo, hi = spec[key]
    if value_mm < lo:
        return {"status": "warn_low", "message": f"{item}.{dim}={value_mm}mm below min {lo}mm."}
    if value_mm > hi:
        return {"status": "warn_high", "message": f"{item}.{dim}={value_mm}mm above max {hi}mm."}
    return {"status": "ok", "message": f"Within {lo}-{hi}mm."}
