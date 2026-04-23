"""Manufacturing constraints — tolerances, joinery, lead times, MOQs.

Per BRD Layer 1C. Units in millimetres where applicable.
"""

from __future__ import annotations

# Tolerance bands (mm) per BRD.
TOLERANCES: dict[str, dict] = {
    "structural": {"+-mm": 1.0, "notes": "Load-bearing joints, frames."},
    "cosmetic": {"+-mm": 2.0, "notes": "Visible surfaces, panels."},
    "material_thickness": {"+-mm": 0.5, "notes": "Sheet stock, veneer."},
    "hardware_placement": {"+-mm": 5.0, "notes": "Knob, handle, hinge lines."},
    "woodworking_precision": {"+-mm": 0.5, "notes": "CNC joinery, dowel."},
    "woodworking_standard": {"+-mm": 2.0, "notes": "Hand + power tool shop."},
    "metal_structural": {"+-mm": 1.0},
    "metal_cosmetic": {"+-mm": 2.0},
    "upholstery_foam": {"+-mm": 5.0},
}

# Woodworking joinery options with structural + aesthetic notes.
JOINERY: dict[str, dict] = {
    "mortise_tenon": {
        "strength": "very high",
        "difficulty": "high",
        "use": "chair and table frames, structural",
        "tolerance_mm": 0.5,
    },
    "dovetail": {
        "strength": "high (tension)",
        "difficulty": "high",
        "use": "drawer joints, showcase edges",
        "tolerance_mm": 0.5,
    },
    "pocket_hole": {
        "strength": "medium",
        "difficulty": "low",
        "use": "cabinet carcasses, hidden joints",
        "tolerance_mm": 1.0,
    },
    "dowel": {
        "strength": "medium",
        "difficulty": "medium",
        "use": "panel-to-panel, leg-to-apron",
        "tolerance_mm": 0.5,
    },
    "biscuit": {
        "strength": "low-medium",
        "difficulty": "low",
        "use": "panel alignment",
        "tolerance_mm": 1.0,
    },
    "butt_screw": {
        "strength": "low",
        "difficulty": "very low",
        "use": "utility, knockdown furniture",
        "tolerance_mm": 2.0,
    },
    "finger_joint": {
        "strength": "high",
        "difficulty": "medium",
        "use": "box corners, shelving",
        "tolerance_mm": 0.5,
    },
}

# Welding / metal fabrication specs.
WELDING: dict[str, dict] = {
    "GMAW_MIG": {
        "use": "steel structural, high throughput",
        "quality": "good with proper shielding",
    },
    "GTAW_TIG": {
        "use": "stainless, aluminium, visible welds",
        "quality": "highest; slower",
    },
    "brazing": {
        "use": "brass, copper joinery",
        "quality": "aesthetic",
    },
    "spot_weld": {
        "use": "sheet metal assemblies",
    },
}

# Minimum bending radius rule.
BENDING_RULE: dict[str, str] = {
    "rule": "R_min >= 2.5 * thickness",
    "notes": "Tighter radius risks cracking; use press brake with matching die.",
}

# Lead times & MOQ per BRD.
LEAD_TIMES_WEEKS: dict[str, tuple[int, int]] = {
    "woodworking_furniture": (4, 8),
    "metal_fabrication": (6, 10),
    "upholstery_post_frame": (3, 6),
    "custom_cast_hardware": (6, 10),
    "powder_coat_job_shop": (1, 2),
    "veneer_pressing": (1, 2),
}

MOQ: dict[str, int] = {
    "woodworking_small_batch": 1,
    "metal_small_batch": 1,
    "cast_hardware": 50,             # typical casting run
    "custom_fabric_weave": 30,        # metres
    "custom_foam_pour": 1,
}

# Quality gates per BRD.
QA_GATES: list[dict] = [
    {"stage": "material_inspection", "check": "density/grade, moisture, finish uniformity"},
    {"stage": "dimension_verification", "check": "+-1mm structural, +-2mm cosmetic"},
    {"stage": "finish_inspection", "check": "colour match, sheen, surface flaws"},
    {"stage": "assembly_check", "check": "joint tightness, movement, alignment"},
    {"stage": "safety_load_test", "check": "stability, cyclic load, weight capacity"},
]

# Upholstery detail.
UPHOLSTERY_SPEC: dict[str, dict] = {
    "webbing_tension_kg_per_inch": (5, 8),
    "stitch_density_per_inch": (4, 6),
    "foam_tolerance_mm": 5,
}


def tolerance_for(category: str) -> float | None:
    spec = TOLERANCES.get(category)
    return spec["+-mm"] if spec else None


def lead_time_for(category: str) -> tuple[int, int] | None:
    return LEAD_TIMES_WEEKS.get(category)
