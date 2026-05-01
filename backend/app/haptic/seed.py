"""Deterministic seed-row builders for the Stage 9 haptic catalog.

Pure functions — no DB, no network. The Stage 9 migration calls
these in ``upgrade()`` and ``op.bulk_insert``s the rows into the
six haptic tables.

Source values
-------------
- BRD §Layer 7 examples are honoured verbatim:
    * walnut surface temperature → 28 °C
    * leather surface temperature → 32 °C
    * wood friction coefficient → 0.35
    * leather friction coefficient → 0.40
    * chair seat-height range → 18–22 in (457–559 mm)
- Other values cite engineering tables in the comments. Friction
  coefficients are static-friction with the human fingertip,
  measured at room temperature on dry surfaces. Surface temps
  assume a 22 °C ambient room — they reflect the *perceived*
  temperature against skin (low-conductivity = warmer feel).
- Densities are bulk densities (kg/m³) for the dominant material
  layer. Used by the haptic system to derive perceived weight when
  the user picks a virtual object up.

Texture codes follow ``{material}_{pattern}_{NNN}`` — a stable
3-digit ordinal so hardware drivers can identify a texture by its
code without parsing the name.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.haptic import GENERIC_MATERIAL_KEY


# ─────────────────────────────────────────────────────────────────────
# Material catalog — keys map to the design-graph ``material`` field.
# ─────────────────────────────────────────────────────────────────────

# Each entry: (material_key, display_name, texture_code, signature,
#              temperature_c, friction_coef, friction_condition,
#              firmness_scale, density_kg_m3, source)
_MATERIALS: list[tuple[
    str, str, str, dict[str, Any], float, float, str, str, float, str,
]] = [
    # Hardwoods — BRD anchors walnut to 28 °C / 0.35 friction.
    (
        "walnut", "Walnut grain",
        "walnut_grain_001",
        {"pattern": "linear_grain", "grain_freq_per_cm": 6,
         "amplitude_um": 80, "direction": "with_grain"},
        28.0, 0.35, "dry_room_temp",
        "firm", 660.0,
        "BRD §Layer 7; Wood Handbook (USDA FPL-GTR-190)",
    ),
    (
        "oak", "Oak grain",
        "oak_grain_002",
        {"pattern": "linear_grain", "grain_freq_per_cm": 4,
         "amplitude_um": 120, "direction": "with_grain"},
        27.0, 0.35, "dry_room_temp",
        "firm", 720.0,
        "Wood Handbook (USDA FPL-GTR-190)",
    ),
    (
        "teak", "Teak grain",
        "teak_grain_003",
        {"pattern": "linear_grain", "grain_freq_per_cm": 8,
         "amplitude_um": 60, "direction": "with_grain"},
        27.0, 0.35, "dry_room_temp",
        "firm", 660.0,
        "Wood Handbook (USDA FPL-GTR-190)",
    ),
    (
        "mahogany", "Mahogany grain",
        "mahogany_grain_004",
        {"pattern": "linear_grain", "grain_freq_per_cm": 5,
         "amplitude_um": 70, "direction": "with_grain"},
        27.0, 0.35, "dry_room_temp",
        "firm", 700.0,
        "Wood Handbook (USDA FPL-GTR-190)",
    ),
    # Soft surfaces — BRD anchors leather to 32 °C / 0.40 friction.
    (
        "leather", "Natural leather",
        "leather_natural_005",
        {"pattern": "fine_pebble", "amplitude_um": 50,
         "pebble_size_mm": 0.6},
        32.0, 0.40, "dry_room_temp",
        "soft", 860.0,
        "BRD §Layer 7; Tribology of Leather (Adams 1995)",
    ),
    (
        "fabric_cotton", "Woven cotton fabric",
        "fabric_woven_006",
        {"pattern": "weave", "thread_count_per_cm": 30,
         "amplitude_um": 30},
        29.0, 0.45, "dry_room_temp",
        "soft", 200.0,
        "Textile friction tables (Hu 2008)",
    ),
    # Hard / cool surfaces.
    (
        "glass", "Smooth glass",
        "glass_smooth_007",
        {"pattern": "smooth", "amplitude_um": 0,
         "transparency": True},
        22.0, 0.15, "dry_room_temp",
        "firm", 2500.0,
        "Engineering ToolBox — friction & thermal tables",
    ),
    (
        "steel", "Brushed stainless steel",
        "steel_brushed_008",
        {"pattern": "linear_brush", "amplitude_um": 5,
         "direction": "longitudinal"},
        21.0, 0.18, "dry_room_temp",
        "firm", 7850.0,
        "ASM Handbook Vol. 18 (Friction, Lubrication & Wear)",
    ),
    (
        "brass", "Polished brass",
        "brass_polished_009",
        {"pattern": "smooth", "amplitude_um": 1},
        22.0, 0.16, "dry_room_temp",
        "firm", 8500.0,
        "ASM Handbook Vol. 18",
    ),
    (
        "marble", "Polished marble",
        "marble_polished_010",
        {"pattern": "smooth_with_veins", "amplitude_um": 2,
         "vein_density_per_cm2": 0.3},
        23.0, 0.20, "dry_room_temp",
        "firm", 2700.0,
        "Stone friction tables (Pavlovic 2014)",
    ),
    (
        "concrete", "Textured concrete",
        "concrete_textured_011",
        {"pattern": "rough", "amplitude_um": 200,
         "aggregate_size_mm": 4},
        22.0, 0.40, "dry_room_temp",
        "firm", 2400.0,
        "ACI 318 Concrete surface friction tables",
    ),
    # Engineered wood.
    (
        "plywood", "Sanded plywood",
        "plywood_smooth_012",
        {"pattern": "linear_grain", "grain_freq_per_cm": 3,
         "amplitude_um": 40},
        26.0, 0.40, "dry_room_temp",
        "medium", 600.0,
        "Wood Handbook (USDA FPL-GTR-190)",
    ),
    # Generic fallback — used by the validator when a design graph
    # references a material with no profile in the catalog. Picked
    # for safety: medium friction, room-neutral temperature, medium
    # firmness. Won't feel right but won't damage the haptic arm.
    (
        GENERIC_MATERIAL_KEY, "Generic surface",
        "generic_neutral_999",
        {"pattern": "smooth", "amplitude_um": 10},
        24.0, 0.30, "dry_room_temp",
        "medium", 1000.0,
        "Stage 9 generic fallback — no source citation needed",
    ),
]


def _new_id() -> str:
    """32-char hex id matching the codebase's ``UUIDMixin`` PK shape."""
    return uuid4().hex


def build_texture_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_textures``.

    One row per material — every material has exactly one canonical
    texture profile. The ``code`` column is unique and stable across
    catalog versions; hardware drivers reference textures by code.
    """
    rows: list[dict[str, Any]] = []
    for (
        material_key, display_name, code, signature,
        _temp, _fr, _fr_cond, _firm, _density, _source,
    ) in _MATERIALS:
        rows.append({
            "id": _new_id(),
            "name": display_name,
            "code": code,
            "material_id": material_key,
            "signature_data": signature,
        })
    return rows


def build_thermal_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_thermal``.

    Surface temperature in °C *as perceived by skin* against a 22 °C
    ambient room. Driven by material thermal effusivity (low =
    feels warm, high = feels cool). BRD anchors walnut→28, leather→32.
    """
    rows: list[dict[str, Any]] = []
    for (
        material_key, _name, _code, _sig,
        temp_c, _fr, _fr_cond, _firm, _density, source,
    ) in _MATERIALS:
        rows.append({
            "id": _new_id(),
            "material_id": material_key,
            "temperature_celsius": float(temp_c),
            "source": source,
        })
    return rows


def build_friction_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_friction``.

    Static friction coefficient between human fingertip and a dry
    surface at room temperature. BRD anchors wood→0.35, leather→0.40.
    """
    rows: list[dict[str, Any]] = []
    for (
        material_key, _name, _code, _sig,
        _temp, fr_coef, fr_condition, _firm, _density, _source,
    ) in _MATERIALS:
        rows.append({
            "id": _new_id(),
            "material_id": material_key,
            "coefficient": float(fr_coef),
            "condition": fr_condition,
        })
    return rows


def build_firmness_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_firmness``.

    Firmness scale (soft / medium / firm) plus bulk density for
    perceived weight when the haptic arm lifts virtual objects.
    """
    rows: list[dict[str, Any]] = []
    for (
        material_key, _name, _code, _sig,
        _temp, _fr, _fr_cond, firm_scale, density_kg_m3, _source,
    ) in _MATERIALS:
        rows.append({
            "id": _new_id(),
            "material_id": material_key,
            "firmness_scale": firm_scale,
            "density": float(density_kg_m3),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────
# Dimension rules — per object type.
# ─────────────────────────────────────────────────────────────────────


# Each entry: (object_type, adjustable_axes, ranges, feedback_curve)
# - ranges: per-axis {min_mm, max_mm, step_mm}
# - feedback_curve: declarative description of how dimension changes
#   propagate (cost / proportional constraints).
#
# BRD anchors: chair seat height 18–22 in → 457–559 mm.
_DIMENSION_RULES: list[tuple[
    str, list[str], dict[str, Any], dict[str, Any],
]] = [
    (
        "chair",
        ["seat_height", "seat_depth", "seat_width"],
        {
            "seat_height": {"min_mm": 457, "max_mm": 559, "step_mm": 10},
            "seat_depth":  {"min_mm": 380, "max_mm": 480, "step_mm": 10},
            "seat_width":  {"min_mm": 400, "max_mm": 520, "step_mm": 10},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": [
                "maintain_back_to_seat_ratio:1.6_to_2.0",
            ],
            "notes": (
                "Adjusting seat_height drags armrest height proportionally."
            ),
        },
    ),
    (
        "sofa",
        ["seat_depth", "seat_height", "arm_height"],
        {
            "seat_depth":  {"min_mm": 500, "max_mm": 600, "step_mm": 10},
            "seat_height": {"min_mm": 380, "max_mm": 450, "step_mm": 10},
            "arm_height":  {"min_mm": 600, "max_mm": 700, "step_mm": 10},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": ["arm_height_above_seat_height_by_min_200_mm"],
        },
    ),
    (
        "dining_table",
        ["height", "length", "depth"],
        {
            "height": {"min_mm": 720, "max_mm": 760, "step_mm": 5},
            "length": {"min_mm": 1200, "max_mm": 2400, "step_mm": 100},
            "depth":  {"min_mm": 800, "max_mm": 1100, "step_mm": 50},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": ["maintain_top_thickness_25_to_50_mm"],
        },
    ),
    (
        "desk",
        ["height", "depth", "width"],
        {
            "height": {"min_mm": 700, "max_mm": 760, "step_mm": 5},
            "depth":  {"min_mm": 600, "max_mm": 800, "step_mm": 50},
            "width":  {"min_mm": 1000, "max_mm": 1800, "step_mm": 100},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": ["leg_clearance_min_640_mm"],
        },
    ),
    (
        "bed",
        ["mattress_height", "frame_length", "frame_width"],
        {
            "mattress_height": {"min_mm": 350, "max_mm": 600, "step_mm": 25},
            "frame_length":    {"min_mm": 1900, "max_mm": 2200, "step_mm": 50},
            "frame_width":     {"min_mm": 900,  "max_mm": 1830, "step_mm": 50},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": ["mattress_height_above_floor_min_350_mm"],
        },
    ),
    (
        "shelf",
        ["shelf_spacing", "depth", "width"],
        {
            "shelf_spacing": {"min_mm": 200, "max_mm": 400, "step_mm": 25},
            "depth":         {"min_mm": 250, "max_mm": 450, "step_mm": 25},
            "width":         {"min_mm": 600, "max_mm": 1800, "step_mm": 100},
        },
        {
            "kind": "linear",
            "constraints": [],
        },
    ),
    (
        "door",
        ["width", "height"],
        {
            "width":  {"min_mm": 800, "max_mm": 1000, "step_mm": 50},
            "height": {"min_mm": 2000, "max_mm": 2400, "step_mm": 100},
        },
        {
            "kind": "linear_with_constraints",
            "constraints": ["aspect_ratio_height_over_width_min_2.0"],
        },
    ),
    (
        "window",
        ["width", "height", "sill_height"],
        {
            "width":       {"min_mm": 600, "max_mm": 1800, "step_mm": 100},
            "height":      {"min_mm": 600, "max_mm": 1500, "step_mm": 100},
            "sill_height": {"min_mm": 800, "max_mm": 1100, "step_mm": 50},
        },
        {
            "kind": "linear",
            "constraints": [],
        },
    ),
]


def build_dimension_rule_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_dimension_rules``.

    One row per furniture / architectural object type. The haptic
    arm reads ``ranges`` to know how far it can move adjustment
    sliders, and ``feedback_curve`` to know which proportions stay
    locked while the user adjusts.
    """
    return [
        {
            "id": _new_id(),
            "object_type": object_type,
            "adjustable_axes": list(axes),
            "ranges": dict(ranges),
            "feedback_curve": dict(curve),
        }
        for object_type, axes, ranges, curve in _DIMENSION_RULES
    ]


# ─────────────────────────────────────────────────────────────────────
# Feedback loops — declarative rules tying dimension/material changes
# to cost or proportional consequences.
# ─────────────────────────────────────────────────────────────────────


# Each entry: (rule_key, trigger, response, formula)
# - rule_key: stable namespaced id; hardware drivers index by this
# - trigger: structured "what change activates the rule"
# - response: structured "what consequence the rule emits"
# - formula: human-readable formula string (BRD calls this out
#   explicitly — "When height changes by 1cm, cost changes by ₹X")
_FEEDBACK_LOOPS: list[tuple[
    str, dict[str, Any], dict[str, Any], str,
]] = [
    # Per BRD: "When height changes by 1cm, cost changes by ₹X"
    (
        "chair.seat_height.cost_per_cm",
        {"object_type": "chair", "axis": "seat_height", "delta_unit": "cm"},
        {"target": "cost_inr", "kind": "linear", "slope_per_unit": 50},
        "ΔCost(INR) = 50 × ΔSeatHeight(cm)",
    ),
    (
        "dining_table.height.cost_per_cm",
        {"object_type": "dining_table", "axis": "height", "delta_unit": "cm"},
        {"target": "cost_inr", "kind": "linear", "slope_per_unit": 80},
        "ΔCost(INR) = 80 × ΔHeight(cm)",
    ),
    (
        "desk.height.cost_per_cm",
        {"object_type": "desk", "axis": "height", "delta_unit": "cm"},
        {"target": "cost_inr", "kind": "linear", "slope_per_unit": 70},
        "ΔCost(INR) = 70 × ΔHeight(cm)",
    ),
    # Per BRD: "When material changes from walnut to oak, cost -₹Y"
    (
        "material.swap.walnut_to_oak",
        {"axis": "material", "from": "walnut", "to": "oak"},
        {"target": "cost_inr", "kind": "step", "delta": -1500},
        "ΔCost(INR) = -1500",
    ),
    (
        "material.swap.oak_to_walnut",
        {"axis": "material", "from": "oak", "to": "walnut"},
        {"target": "cost_inr", "kind": "step", "delta": 1500},
        "ΔCost(INR) = +1500",
    ),
    (
        "material.swap.fabric_cotton_to_leather",
        {"axis": "material", "from": "fabric_cotton", "to": "leather"},
        {"target": "cost_inr", "kind": "step", "delta": 15000},
        "ΔCost(INR) = +15000",
    ),
    (
        "material.swap.leather_to_fabric_cotton",
        {"axis": "material", "from": "leather", "to": "fabric_cotton"},
        {"target": "cost_inr", "kind": "step", "delta": -15000},
        "ΔCost(INR) = -15000",
    ),
    # Per BRD: "Proportions maintained within design intent"
    (
        "proportion.chair.back_to_seat_ratio",
        {"object_type": "chair", "axis": "seat_depth", "delta_unit": "any"},
        {
            "target": "back_height",
            "kind": "proportional",
            "ratio_min": 1.6,
            "ratio_max": 2.0,
        },
        "BackHeight ∈ [1.6×SeatDepth, 2.0×SeatDepth]",
    ),
    (
        "proportion.door.aspect_ratio",
        {"object_type": "door", "axis": "width", "delta_unit": "any"},
        {
            "target": "height",
            "kind": "proportional",
            "ratio_min": 2.0,
            "ratio_max": 3.0,
        },
        "Height ∈ [2.0×Width, 3.0×Width]",
    ),
]


def build_feedback_loop_rows() -> list[dict[str, Any]]:
    """Rows for ``haptic_feedback_loops``.

    Per BRD §Layer 7: rules encoded for haptic response. Each rule
    pairs a *trigger* (what change activates it) with a *response*
    (what consequence the haptic system should reflect).
    """
    return [
        {
            "id": _new_id(),
            "rule_key": rule_key,
            "trigger": dict(trigger),
            "response": dict(response),
            "formula": formula,
        }
        for rule_key, trigger, response, formula in _FEEDBACK_LOOPS
    ]


# ─────────────────────────────────────────────────────────────────────
# Public summaries — used by docs and tests.
# ─────────────────────────────────────────────────────────────────────


def known_material_keys() -> list[str]:
    """All material keys the seed catalog covers (incl. ``generic``)."""
    return [m[0] for m in _MATERIALS]


def known_object_types() -> list[str]:
    """All object types the seed catalog has dimension rules for."""
    return [r[0] for r in _DIMENSION_RULES]


def known_feedback_rule_keys() -> list[str]:
    """All feedback-loop ``rule_key`` values in the seed catalog."""
    return [r[0] for r in _FEEDBACK_LOOPS]
