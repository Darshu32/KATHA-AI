"""Manufacturing constraints — tolerances, joinery, lead times, MOQs.

Per BRD Layer 1C. Units in millimetres where applicable.
"""

from __future__ import annotations

# BRD 3A — Precision Requirements (universal tolerance bands)
#   Structural dimensions: ±1 mm
#   Cosmetic dimensions:   ±2 mm
#   Material thickness:    ±0.5 mm
#   Hardware placement:    ±5 mm
# Used by every drawing endpoint to self-report compliance and by the
# QA gate "dimension_verification" to grade actual production output.
PRECISION_REQUIREMENTS_BRD: dict = {
    "structural_mm": 1.0,
    "cosmetic_mm": 2.0,
    "material_thickness_mm": 0.5,
    "hardware_placement_mm": 5.0,
}


# BRD 1C — Woodworking canonical spec
#   Joinery methods in scope: mortise–tenon, dovetail, pocket-hole
#   Machining tolerances: ±2 mm standard, ±0.5 mm precision
#   Lead time: 4–8 weeks order-to-delivery
#   MOQ: 1 piece (small-batch friendly)
WOODWORKING_BRD_SPEC: dict = {
    "joinery_core": ("mortise_tenon", "dovetail", "pocket_hole"),
    "tolerance_standard_mm": 2.0,
    "tolerance_precision_mm": 0.5,
    "lead_time_weeks": (4, 8),
    "moq_pieces": 1,
}

# Tolerance bands (mm) per BRD.
TOLERANCES: dict[str, dict] = {
    "structural": {"+-mm": 1.0, "notes": "Load-bearing joints, frames."},
    "cosmetic": {"+-mm": 2.0, "notes": "Visible surfaces, panels."},
    "material_thickness": {"+-mm": 0.5, "notes": "Sheet stock, veneer."},
    "hardware_placement": {"+-mm": 5.0, "notes": "Knob, handle, hinge lines."},
    "woodworking_precision": {"+-mm": 0.5, "notes": "CNC joinery, dowel — BRD precision."},
    "woodworking_standard": {"+-mm": 2.0, "notes": "Hand + power tool shop — BRD standard."},
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

# BRD 1C — Metal Fabrication canonical spec
#   Welding: GMAW / GTAW for structural integrity
#   Bending radius: R_min = 2.5 × thickness
#   Powder-coat cure: 10–15 min at 200 °C  (recipe stored in materials.FINISHES["powder_coat"])
#   Lead time: 6–10 weeks
#   Precision: ±1 mm structural, ±2 mm cosmetic
METAL_FABRICATION_BRD_SPEC: dict = {
    "structural_welding": ("GMAW_MIG", "GTAW_TIG"),
    "bending_radius_rule": "R_min = 2.5 × thickness",
    "powder_coat_cure_temp_c": 200,
    "powder_coat_cure_time_min": (10, 15),
    "lead_time_weeks": (6, 10),
    "tolerance_structural_mm": 1.0,
    "tolerance_cosmetic_mm": 2.0,
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

# BRD 1C — Quality Gates canonical spec
#   1. Material inspection  (density, finish uniformity)
#   2. Dimension verification (±1 mm structural, ±2 mm cosmetic)
#   3. Finish inspection  (colour match, surface uniformity)
#   4. Assembly check  (joints tight, movement smooth)
#   5. Safety testing  (stability, durability under load)
QUALITY_GATES_BRD_SPEC: tuple[str, ...] = (
    "material_inspection",
    "dimension_verification",
    "finish_inspection",
    "assembly_check",
    "safety_testing",
)

# Quality gates per BRD (expanded acceptance criteria).
QA_GATES: list[dict] = [
    {
        "stage": "material_inspection",
        "brd_scope": "density, finish uniformity",
        "checks": [
            "density / grade match spec sheet",
            "moisture content in range (wood)",
            "finish uniformity — no streaks, bubbles, or orange peel",
        ],
    },
    {
        "stage": "dimension_verification",
        "brd_scope": "±1 mm structural, ±2 mm cosmetic",
        "checks": [
            "structural members within ±1 mm of drawing",
            "visible / cosmetic surfaces within ±2 mm of drawing",
            "squareness across diagonals",
        ],
    },
    {
        "stage": "finish_inspection",
        "brd_scope": "colour match, surface uniformity",
        "checks": [
            "colour match to approved sample (Delta-E ≤ 2.0)",
            "sheen level consistent across surfaces",
            "no surface flaws — scratches, inclusions, uneven coverage",
        ],
    },
    {
        "stage": "assembly_check",
        "brd_scope": "joints tight, movement smooth",
        "checks": [
            "joint tightness — no visible gaps, no rocking",
            "drawers / doors / hinges move smoothly full travel",
            "alignment — parallel edges, flush faces",
        ],
    },
    {
        "stage": "safety_testing",
        "brd_scope": "stability, durability under load",
        "checks": [
            "stability — no tip under 10° off-axis or rated horizontal load",
            "static load test to rated capacity + safety factor",
            "cyclic load / fatigue where applicable (seating, hinges)",
        ],
    },
]

# BRD 1C — Upholstery Assembly canonical spec
#   Foam cutting tolerance: ±5 mm
#   Webbing tension: 5–8 kg/linear inch
#   Stitch density: 4–6 stitches per inch
#   Lead time: 3–6 weeks (post-frame completion)
#   QC: seam straightness, zipper placement, piping alignment
UPHOLSTERY_ASSEMBLY_BRD_SPEC: dict = {
    "foam_tolerance_mm": 5,
    "webbing_tension_kg_per_inch": (5, 8),
    "stitch_density_per_inch": (4, 6),
    "lead_time_weeks": (3, 6),
    "qc_checks": (
        "seam_straightness",
        "zipper_placement",
        "piping_alignment",
    ),
}

# Upholstery detail.
UPHOLSTERY_SPEC: dict[str, dict] = {
    "webbing_tension_kg_per_inch": (5, 8),      # BRD: 5–8 kg/linear inch
    "stitch_density_per_inch": (4, 6),           # BRD: 4–6 stitches/in
    "foam_tolerance_mm": 5,                      # BRD: ±5 mm foam cutting
    "qc_checks": [
        {"check": "seam_straightness",    "accept": "≤ ±2 mm deviation over 300 mm run"},
        {"check": "zipper_placement",     "accept": "centred, flush, teeth engage full length"},
        {"check": "piping_alignment",     "accept": "continuous, no gaps at seams / corners"},
    ],
}


def tolerance_for(category: str) -> float | None:
    spec = TOLERANCES.get(category)
    return spec["+-mm"] if spec else None


def lead_time_for(category: str) -> tuple[int, int] | None:
    return LEAD_TIMES_WEEKS.get(category)
