"""Building codes — NBC India (Part references), ECBC, accessibility basics.

⚠️ STAGE 3E DEPRECATION NOTICE — April 2026
--------------------------------------------
The dicts in this file have been migrated to the ``building_standards``
DB table (category=``code``, jurisdiction=``india_nbc``). DB-backed
async lookups live in :mod:`app.services.standards.codes_lookup`
(``nbc_minimum_room_dimensions``, ``check_room_against_nbc``,
``get_ecbc_targets``, ``get_accessibility``, ``get_fire_safety``).

Why this file still exists
  1. Source for ``0011_stage3e_codes_seed``.
  2. Sync fallback for legacy consumers (notably ``summary.py`` which
     still injects NBC clauses into LLM prompts directly). Stage 4+
     migrates the prompt builder to async.

DO NOT update values here. Use ``POST /admin/standards/code/<slug>``
so the change is versioned + audited and visible to the agent
immediately.

---

Not a legal substitute; summary of key rules relevant to design generation.
"""

from __future__ import annotations

# ── NBC India (National Building Code, 2016) key rules ───────────────────────
NBC_INDIA: dict[str, dict] = {
    "minimum_room_dimensions": {
        "part": "Part 3",
        "habitable_room_min_area_m2": 9.5,
        "habitable_room_min_short_side_m": 2.4,
        "habitable_room_min_height_m": 2.75,
        "kitchen_min_area_m2": 4.5,
        "kitchen_min_short_side_m": 1.5,
        "bathroom_min_area_m2": 1.8,
        "wc_min_area_m2": 1.1,
    },
    "ventilation": {
        "part": "Part 8",
        "openable_area_percent_floor": 10.0,
        "notes": "Window openable area >= 10% of floor for habitable rooms.",
    },
    "natural_light": {
        "part": "Part 8",
        "glazing_percent_floor": 15.0,
        "notes": "Window glazing >= 15% of floor; internal rooms need skylights/courts.",
    },
    "staircase_residential": {
        "part": "Part 4",
        "rise_max_mm": 190,
        "tread_min_mm": 250,
        "width_min_mm": 900,
        "headroom_min_mm": 2100,
    },
    "staircase_public": {
        "part": "Part 4",
        "rise_max_mm": 150,
        "tread_min_mm": 300,
        "width_min_mm": 1500,
    },
    "fire_egress": {
        "part": "Part 4",
        "max_travel_residential_m": 30,
        "max_travel_commercial_m": 30,        # more for sprinklered
        "min_exit_count_over_500m2_floor": 2,
        "fire_door_rating_min_hr": 2,
        "corridor_min_width_mm": 1500,
    },
    "parking": {
        "part": "Part 3",
        "residential_ECS_per_flat": 1.0,      # varies by city
        "office_ECS_per_100m2": 2.0,
        "ecs_space_m": "2.5 x 5.0",
    },
}

# ── ECBC (Energy Conservation Building Code) ─────────────────────────────────
ECBC: dict[str, dict] = {
    "envelope_U_value_wall_w_m2k": 0.40,
    "envelope_U_value_roof_w_m2k": 0.33,
    "window_wall_ratio_max": 0.40,
    "lighting_power_density_office_w_m2": 10.5,
    "lighting_power_density_retail_w_m2": 15.0,
    "cop_chiller_min": 2.8,
    "notes": "Applies to buildings with connected load >= 100 kW or 120 kVA.",
}

# ── Accessibility (Harmonised Guidelines 2021 + NBC Part 3) ──────────────────
ACCESSIBILITY: dict[str, dict] = {
    "doorway_clear_width_mm": 900,
    "corridor_min_width_mm": 1500,
    "ramp_slope_max_ratio": 1 / 12,
    "ramp_landing_every_m": 9.0,
    "handrail_height_mm": (865, 965),
    "wc_accessible_clear_floor_mm": "1500 x 1500",
    "counter_height_accessible_mm": 800,
    "switch_height_mm": (900, 1100),
    "signage_tactile_min_font_mm": 16,
}

# ── Fire safety quick reference ──────────────────────────────────────────────
FIRE_SAFETY: dict[str, dict] = {
    "smoke_detector": "required all habitable floors",
    "sprinkler_trigger": {
        "commercial_m2": 500,
        "residential_height_m": 15,
    },
    "fire_extinguisher_per_m2": 1 / 200,
    "fire_hose_reel_per_m2": 1 / 1000,
    "exit_sign_illumination_lux": 5,
}


def check_room_against_nbc(room_type: str, area_m2: float, short_side_m: float, height_m: float) -> list[dict]:
    """Return list of violations vs NBC minimum-room-dimensions."""
    nbc = NBC_INDIA["minimum_room_dimensions"]
    issues: list[dict] = []
    key = f"{room_type}_min_area_m2"
    if room_type in {"bedroom", "living_room", "dining_room", "study"}:
        if area_m2 < nbc["habitable_room_min_area_m2"]:
            issues.append({"code": "NBC Part 3", "issue": f"Area {area_m2}m^2 < habitable min {nbc['habitable_room_min_area_m2']}"})
        if short_side_m < nbc["habitable_room_min_short_side_m"]:
            issues.append({"code": "NBC Part 3", "issue": f"Short side {short_side_m}m < {nbc['habitable_room_min_short_side_m']}"})
        if height_m < nbc["habitable_room_min_height_m"]:
            issues.append({"code": "NBC Part 3", "issue": f"Height {height_m}m < {nbc['habitable_room_min_height_m']}"})
    elif room_type == "kitchen":
        if area_m2 < nbc["kitchen_min_area_m2"]:
            issues.append({"code": "NBC Part 3", "issue": f"Kitchen area {area_m2} < {nbc['kitchen_min_area_m2']}"})
    elif room_type == "bathroom":
        if area_m2 < nbc["bathroom_min_area_m2"]:
            issues.append({"code": "NBC Part 3", "issue": f"Bathroom area {area_m2} < {nbc['bathroom_min_area_m2']}"})
    return issues
