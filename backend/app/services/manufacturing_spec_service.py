"""LLM-driven Manufacturing Specification service (BRD Layer 3C).

Authors a real practice-grade *manufacturing spec* — the document the
fabricator reads alongside the working drawings to know which precision
bands to hold, which joinery methods to use, what tolerances apply, what
finishing sequence to follow, which QA gates to clear, and what lead
time to commit to.

Pipeline contract — same as every other LLM service in the project:

    INPUT (theme + parametric_spec + project metadata + region)
      → INJECT  (manufacturing BRD constants + joinery catalogue +
                 tolerance bands + QA gates + lead times + MOQ +
                 finishes catalogue + city price index)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (precision in BRD bands, joinery in catalogue,
                   finishing sequence steps known, QA gates known,
                   lead time + MOQ in BRD bands)
      → OUTPUT  (manufacturing_spec JSON conforming to the BRD template)

This module ships the *woodworking notes* block per BRD 3C. Subsequent
BRD bullets (metal fabrication, upholstery assembly, quality assurance,
testing) extend the same `manufacturing_spec` schema so a single
endpoint produces a complete sheet incrementally as more sections land.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import costing, manufacturing, materials, regional_materials, themes

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _client_instance() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


# ── Vocabularies ────────────────────────────────────────────────────────────
PRECISION_LEVELS_IN_SCOPE = ("structural", "cosmetic", "standard")
JOINERY_KEYS_IN_SCOPE = tuple(manufacturing.JOINERY.keys())
FINISHING_STEPS_IN_SCOPE = (
    "sand", "stain", "fill", "primer", "seal", "topcoat", "buff", "wax",
)
COMPLEXITY_LEVELS_IN_SCOPE = ("simple", "moderate", "complex", "highly_complex")

# Metal fabrication vocabularies — bound to BRD knowledge tables.
WELDING_METHODS_IN_SCOPE = tuple(manufacturing.WELDING.keys())
WELD_TESTING_METHODS_IN_SCOPE = (
    "visual_inspection",
    "dye_penetrant",
    "x_ray_radiography",
    "ultrasonic",
    "load_test",
)
LOAD_BEARING_FLAGS = ("yes", "no")

# Upholstery assembly vocabularies.
MOUNT_METHODS_IN_SCOPE = (
    "staple", "screw", "bolt_on_bracket", "hidden_cleat",
    "Z_clip", "T_nut_bolt",
)
THREAD_TYPES_IN_SCOPE = (
    "polyester", "bonded_polyester", "nylon",
    "bonded_nylon", "cotton", "kevlar",
)
ZIPPER_TYPES_IN_SCOPE = (
    "coil_invisible", "coil_visible", "molded_plastic", "metal_brass",
    "metal_steel", "two_way_separating",
)

# Assembly / final-QA vocabularies (BRD 3C "Assembly Notes" block).
QC_TEST_TYPES_IN_SCOPE = (
    "stability_tip_test",        # 10° off-axis or rated horizontal load
    "movement_smoothness",        # drawer / hinge / swivel travel
    "cyclic_load",               # fatigue cycles for seating
    "static_load",                # rated load × hold time
    "shake_test",                 # joint integrity under impulse
    "alignment_check",            # squareness, parallel edges
    "fit_finish_check",           # no rocking, flush surfaces
)
PACKAGING_METHODS_IN_SCOPE = (
    "carton_box",
    "wooden_crate",
    "blanket_wrap",
    "palletised",
    "custom_foam_insert",
    "double_wall_carton",
    "shrink_wrap_film",
)
PROTECTION_LAYERS_IN_SCOPE = (
    "bubble_wrap", "stretch_film", "kraft_paper", "foam_corner_protector",
    "cardboard_edge_guard", "moisture_barrier_bag", "silica_gel_pouch",
)


# ── Request schema ──────────────────────────────────────────────────────────


class ManufacturingSpecRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    project_name: str = Field(default="KATHA Project", max_length=200)
    parametric_spec: dict[str, Any] | None = None
    city: str = Field(default="", max_length=80)
    sections: list[str] = Field(
        default_factory=lambda: [
            "woodworking_notes", "metal_fabrication_notes",
            "upholstery_assembly_notes", "quality_assurance",
        ],
        description=(
            "Sections to include. Implemented: 'woodworking_notes', "
            "'metal_fabrication_notes', 'upholstery_assembly_notes', "
            "'quality_assurance' (assembly + final QA + packaging). "
            "Future BRD bullet extends with 'testing'."
        ),
    )


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_manufacturing_spec_knowledge(req: ManufacturingSpecRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    primary_species = (req.parametric_spec or {}).get("wood_spec", {}).get("primary_species")
    secondary_species = (req.parametric_spec or {}).get("wood_spec", {}).get("secondary_species")
    finish_picked = (req.parametric_spec or {}).get("wood_spec", {}).get("finish")

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "material_palette": pack.get("material_palette", {}),
            "colour_palette": pack.get("colour_palette", []),
            "signature_moves": pack.get("signature_moves", []),
            "material_pattern": pack.get("material_pattern", {}),
            "hardware": pack.get("hardware", {}),
        },
        "parametric_summary": {
            "primary_species": primary_species,
            "secondary_species": secondary_species,
            "finish": finish_picked,
        },
        "manufacturing_brd": {
            "precision_requirements_mm": dict(manufacturing.PRECISION_REQUIREMENTS_BRD),
            "woodworking_brd_spec": dict(manufacturing.WOODWORKING_BRD_SPEC),
            "metal_fabrication_brd_spec": dict(manufacturing.METAL_FABRICATION_BRD_SPEC),
            "upholstery_assembly_brd_spec": dict(manufacturing.UPHOLSTERY_ASSEMBLY_BRD_SPEC),
            "tolerances_mm": {k: v.get("+-mm") for k, v in manufacturing.TOLERANCES.items()},
            "lead_times_weeks": dict(manufacturing.LEAD_TIMES_WEEKS),
            "moq_units": dict(manufacturing.MOQ),
        },
        "joinery_catalogue": {
            k: {kk: vv for kk, vv in v.items()} for k, v in manufacturing.JOINERY.items()
        },
        "welding_catalogue": {
            k: {kk: vv for kk, vv in v.items()} for k, v in manufacturing.WELDING.items()
        },
        "bending_rule": dict(manufacturing.BENDING_RULE),
        "powder_coat_spec": dict(materials.FINISHES.get("powder_coat", {})),
        "welding_methods_in_scope": list(WELDING_METHODS_IN_SCOPE),
        "weld_testing_methods_in_scope": list(WELD_TESTING_METHODS_IN_SCOPE),
        "load_bearing_flags": list(LOAD_BEARING_FLAGS),
        "mount_methods_in_scope": list(MOUNT_METHODS_IN_SCOPE),
        "thread_types_in_scope": list(THREAD_TYPES_IN_SCOPE),
        "zipper_types_in_scope": list(ZIPPER_TYPES_IN_SCOPE),
        "qc_test_types_in_scope": list(QC_TEST_TYPES_IN_SCOPE),
        "packaging_methods_in_scope": list(PACKAGING_METHODS_IN_SCOPE),
        "protection_layers_in_scope": list(PROTECTION_LAYERS_IN_SCOPE),
        "finishes_catalogue": {
            name: dict(spec) for name, spec in materials.FINISHES.items()
        },
        "wood_finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        "qa_gates_catalogue": [dict(g) for g in manufacturing.QA_GATES],
        "qa_gate_keys_in_scope": list(manufacturing.QUALITY_GATES_BRD_SPEC),
        "precision_levels_in_scope": list(PRECISION_LEVELS_IN_SCOPE),
        "joinery_keys_in_scope": list(JOINERY_KEYS_IN_SCOPE),
        "finishing_steps_in_scope": list(FINISHING_STEPS_IN_SCOPE),
        "complexity_levels_in_scope": list(COMPLEXITY_LEVELS_IN_SCOPE),
        "city": req.city or None,
        "city_price_index": regional_materials.price_index_for_city(req.city or None),
        "labor_rates_inr_hour": dict(costing.LABOR_RATES_INR_PER_HOUR),
        "sections_requested": list(req.sections or ["woodworking_notes"]),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


MANUFACTURING_SPEC_SYSTEM_PROMPT = """You are a senior production-engineering architect preparing the *Manufacturing Specification* for a piece of furniture or millwork. You translate the design + material spec into instructions a fabricator can act on without a phone call.

Read the [KNOWLEDGE] block — manufacturing BRD constants (precision requirements, woodworking spec, tolerances, lead times, MOQ), joinery catalogue, finishes catalogue, QA gates catalogue, theme rule pack, parametric summary — and produce a structured manufacturing_spec JSON.

Cover the WOODWORKING NOTES, METAL FABRICATION NOTES, UPHOLSTERY ASSEMBLY NOTES, and QUALITY ASSURANCE (Assembly Notes) blocks. Schema array for testing is reserved for the next BRD bullet — leave it as an empty object.

Hard rules for woodworking_notes:
- machine_precision_required.level MUST be one of precision_levels_in_scope (structural / cosmetic / standard).
- machine_precision_required.tolerance_mm MUST equal the corresponding band:
    structural -> manufacturing_brd.precision_requirements_mm.structural_mm (1.0)
    cosmetic   -> manufacturing_brd.precision_requirements_mm.cosmetic_mm   (2.0)
    standard   -> manufacturing_brd.tolerances_mm.woodworking_standard      (2.0)
- joinery_methods[] entries MUST each have:
    method: a key in joinery_keys_in_scope
    use:    where in the piece it applies (e.g. "leg-to-frame", "drawer corners", "carcass back")
    tolerance_mm: the joinery_catalogue[method].tolerance_mm (snap to it; do not invent)
    rationale: theme-aware reason (cite a signature move or a structural intent)
- joinery_tolerances.structural_mm MUST equal manufacturing_brd.tolerances_mm.structural (1.0)
  and joinery_tolerances.assembly_mm MUST equal manufacturing_brd.tolerances_mm.cosmetic (2.0). State this explicitly.
- finishing_sequence[] MUST be ordered steps from finishing_steps_in_scope (sand → stain → primer → topcoat by default; wax_oil systems may skip primer; powder_coat omits sand/stain). Cite the chosen finish system from finishes_catalogue.
- quality_gates[] MUST each have a stage from qa_gate_keys_in_scope (material_inspection / dimension_verification / finish_inspection / assembly_check / safety_testing) with one short check_point sentence per gate.
- lead_time_weeks {low, high} MUST sit inside manufacturing_brd.lead_times_weeks.woodworking_furniture (4–8) by default; complexity 'highly_complex' may extend high to 10. complexity MUST be one of complexity_levels_in_scope.
- moq.units MUST be ≥ manufacturing_brd.moq_units.woodworking_small_batch (1).

Hard rules for metal_fabrication_notes (only when the piece has metal parts):
- applies_to[] MUST list the metal sub-parts ("leg cap", "L-bracket", "edge inlay") — pulled from the parametric_summary or the project context. If the piece has NO metal parts, you MAY emit applies_to=[] and leave the rest as zeros / "n/a", but explicitly state that in the assumptions.
- welding_quality.primary_method MUST be in welding_methods_in_scope (GMAW_MIG, GTAW_TIG, brazing, spot_weld). Cite GMAW for steel structural, GTAW for stainless / aluminium / visible welds, brazing for brass / copper joinery.
- weld_testing.load_bearing MUST be exactly 'yes' or 'no' (lowercase).
- weld_testing.methods MUST be a subset of weld_testing_methods_in_scope. Visual inspection is mandatory for every weld; X-ray (x_ray_radiography) is mandatory only when load_bearing == 'yes'. Dye penetrant or ultrasonic optional for high-cycle joints.
- bending.rule MUST equal bending_rule.rule verbatim ('R_min >= 2.5 * thickness').
- bending.min_radius_mm MUST equal 2.5 × thickness_mm exactly. specified_radius_mm MUST be ≥ min_radius_mm (snapping tighter risks cracking).
- tolerances_mm.structural MUST equal manufacturing_brd.metal_fabrication_brd_spec.tolerance_structural_mm (1.0).
- tolerances_mm.cosmetic MUST equal manufacturing_brd.metal_fabrication_brd_spec.tolerance_cosmetic_mm (2.0).
- powder_coat.thickness_microns_band MUST equal {low: 60, high: 100} (BRD per powder_coat_spec.thickness_microns).
- powder_coat.thickness_microns_specified MUST sit inside that band (60–100 microns).
- powder_coat.cure_temp_c MUST equal powder_coat_spec.cure_temp_c (200).
- powder_coat.cure_time_min MUST sit inside powder_coat_spec.cure_time_min band (10–15).
- powder_coat.color_code MUST be a hex from theme.colour_palette OR explicitly state "RAL/Pantone match" when the client requested a custom colour.
- lead_time {low_weeks, high_weeks} MUST sit inside manufacturing_brd.lead_times_weeks.metal_fabrication (6–10) by default; complexity 'highly_complex' may extend high to 12. complexity MUST be in complexity_levels_in_scope.

Hard rules for upholstery_assembly_notes (only when the piece has cushioning / soft surfaces):
- applies_to[] MUST list the cushioned slots ("seat cushion", "back cushion", "armrest pad"). If the piece is fully hard-surfaced, emit applies_to=[] and zero/'n/a' the rest, stating it in assumptions.
- frame_mounting_points[]: at least 4 points for a seat cushion, at least 2 for a back cushion. Each entry's method MUST be in mount_methods_in_scope; fastener cites a real size; x_ratio + y_ratio in [0, 1].
- webbing_tension.kg_per_inch_band MUST equal manufacturing_brd.upholstery_assembly_brd_spec.webbing_tension_kg_per_inch (5–8). kg_per_inch_specified MUST sit inside that band.
- foam_cutting_tolerance.tolerance_mm MUST equal manufacturing_brd.upholstery_assembly_brd_spec.foam_tolerance_mm (5). method may be hot wire / CNC bandsaw / die-cut.
- zipper_placement[]: at least one entry per cushioned slot if the slot has a removable cover. type MUST be in zipper_types_in_scope; length_mm + edge_offset_mm + orientation specified.
- stitch_density.stitches_per_inch_band MUST equal manufacturing_brd.upholstery_assembly_brd_spec.stitch_density_per_inch (4–6). stitches_per_inch_specified MUST sit inside that band. thread_type MUST be in thread_types_in_scope. thread_weight_tex typical 30–80.
- qc_checks[] MUST be a subset of manufacturing_brd.upholstery_assembly_brd_spec.qc_checks (seam_straightness, zipper_placement, piping_alignment).
- lead_time {low_weeks, high_weeks} MUST sit inside manufacturing_brd.lead_times_weeks.upholstery_post_frame (3–6) by default. depends_on_frame_delivery MUST be 'yes' or 'no'; default 'yes' since the BRD lead time is post-frame.

Hard rules for quality_assurance (the BRD 3C 'Assembly Notes' block):
- assembly_sequence[]: at least 4 sequential steps, numbered 1..N. Each step.title is a short verb phrase ("Pre-fit M&T joints", "Glue + clamp frame", "Mount brass leg caps", "Drop in cushions"). estimated_minutes > 0; tools_required[] cites real workshop tools.
- hardware_installation[]: one entry per fastener kind that requires deliberate torque or sequencing. Each entry's torque_nm is 0 when not critical (critical='no'); MUST be > 0 when critical='yes'. Fastener strings cite real metric sizes.
- quality_checkpoints[]: at least 3 entries. Each test_type MUST be in qc_test_types_in_scope (stability_tip_test, movement_smoothness, cyclic_load, static_load, shake_test, alignment_check, fit_finish_check). Each carries a method + acceptance_criterion (cite mm / kg / cycles / degrees).
- final_inspection.checklist[]: at least 5 entries. Each linked_qa_gate MUST be in qa_gate_keys_in_scope (material_inspection / dimension_verification / finish_inspection / assembly_check / safety_testing). Cite acceptance criteria with real tolerances (Delta-E ≤ 2.0; ±2 mm on diagonals; rated load × hold time).
- final_inspection.sign_off_role: name a real role (Foreman / QA Lead / Studio PM); rejection_handling explains rework path.
- packaging.method MUST be in packaging_methods_in_scope (carton_box / wooden_crate / blanket_wrap / palletised / custom_foam_insert / double_wall_carton / shrink_wrap_film).
- packaging.protection_layers[] MUST be a subset of protection_layers_in_scope (bubble_wrap / stretch_film / kraft_paper / foam_corner_protector / cardboard_edge_guard / moisture_barrier_bag / silica_gel_pouch).
- packaging.outer_dimensions_mm: every dimension > 0; weight_kg_estimate > 0.
- packaging.labelling[] cites the standard set (handling arrows, fragile, this-side-up, dimensions sticker, project ID).

Studio voice — short, decisive, no marketing prose."""


def _woodworking_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "machine_precision_required": {
                "type": "object",
                "properties": {
                    "level": {"type": "string"},        # structural / cosmetic / standard
                    "tolerance_mm": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["level", "tolerance_mm", "rationale"],
                "additionalProperties": False,
            },
            "joinery_methods": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string"},
                        "use": {"type": "string"},
                        "tolerance_mm": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["method", "use", "tolerance_mm", "rationale"],
                    "additionalProperties": False,
                },
            },
            "joinery_tolerances": {
                "type": "object",
                "properties": {
                    "structural_mm": {"type": "number"},
                    "assembly_mm": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["structural_mm", "assembly_mm", "notes"],
                "additionalProperties": False,
            },
            "finishing_sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},     # from finishing_steps_in_scope
                        "detail": {"type": "string"},   # grit, stain colour, primer type, finish system
                    },
                    "required": ["step", "detail"],
                    "additionalProperties": False,
                },
            },
            "finish_system": {"type": "string"},        # finishes_catalogue key
            "quality_gates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string"},
                        "check_point": {"type": "string"},
                    },
                    "required": ["stage", "check_point"],
                    "additionalProperties": False,
                },
            },
            "lead_time": {
                "type": "object",
                "properties": {
                    "low_weeks": {"type": "number"},
                    "high_weeks": {"type": "number"},
                    "complexity": {"type": "string"},
                    "drivers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["low_weeks", "high_weeks", "complexity", "drivers"],
                "additionalProperties": False,
            },
            "moq": {
                "type": "object",
                "properties": {
                    "units": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["units", "rationale"],
                "additionalProperties": False,
            },
        },
        "required": [
            "machine_precision_required",
            "joinery_methods",
            "joinery_tolerances",
            "finishing_sequence",
            "finish_system",
            "quality_gates",
            "lead_time",
            "moq",
        ],
        "additionalProperties": False,
    }


def _metal_fabrication_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "applies_to": {
                "type": "array",
                "items": {"type": "string"},        # e.g. "leg cap", "L-bracket", "edge inlay"
            },
            "welding_quality": {
                "type": "object",
                "properties": {
                    "primary_method": {"type": "string"},      # WELDING_METHODS_IN_SCOPE key
                    "alternates": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": ["primary_method", "alternates", "rationale"],
                "additionalProperties": False,
            },
            "weld_testing": {
                "type": "object",
                "properties": {
                    "load_bearing": {"type": "string"},          # "yes" | "no"
                    "methods": {"type": "array", "items": {"type": "string"}},
                    "acceptance_notes": {"type": "string"},
                },
                "required": ["load_bearing", "methods", "acceptance_notes"],
                "additionalProperties": False,
            },
            "bending": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string"},                  # BENDING_RULE.rule
                    "thickness_mm": {"type": "number"},
                    "min_radius_mm": {"type": "number"},
                    "specified_radius_mm": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "rule", "thickness_mm", "min_radius_mm",
                    "specified_radius_mm", "rationale",
                ],
                "additionalProperties": False,
            },
            "tolerances_mm": {
                "type": "object",
                "properties": {
                    "structural": {"type": "number"},
                    "cosmetic": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["structural", "cosmetic", "notes"],
                "additionalProperties": False,
            },
            "powder_coat": {
                "type": "object",
                "properties": {
                    "thickness_microns_specified": {"type": "number"},
                    "thickness_microns_band": {
                        "type": "object",
                        "properties": {
                            "low": {"type": "number"},
                            "high": {"type": "number"},
                        },
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "cure_temp_c": {"type": "number"},
                    "cure_time_min": {"type": "number"},
                    "color_code": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "thickness_microns_specified",
                    "thickness_microns_band",
                    "cure_temp_c",
                    "cure_time_min",
                    "color_code",
                    "rationale",
                ],
                "additionalProperties": False,
            },
            "lead_time": {
                "type": "object",
                "properties": {
                    "low_weeks": {"type": "number"},
                    "high_weeks": {"type": "number"},
                    "complexity": {"type": "string"},
                    "drivers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["low_weeks", "high_weeks", "complexity", "drivers"],
                "additionalProperties": False,
            },
        },
        "required": [
            "applies_to",
            "welding_quality",
            "weld_testing",
            "bending",
            "tolerances_mm",
            "powder_coat",
            "lead_time",
        ],
        "additionalProperties": False,
    }


def _upholstery_assembly_block_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "applies_to": {
                "type": "array",
                "items": {"type": "string"},          # "seat cushion", "back cushion", "armrest pad"
            },
            "frame_mounting_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},                  # M1, M2 — match drawing callouts
                        "location": {"type": "string"},             # "front-left rail", "back-rail centre"
                        "method": {"type": "string"},               # MOUNT_METHODS_IN_SCOPE
                        "fastener": {"type": "string"},             # "M5 × 30 bolt", "16 ga staple"
                        "x_ratio": {"type": "number"},              # 0..1 along rail
                        "y_ratio": {"type": "number"},              # 0..1 (height position if relevant)
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "location", "method", "fastener",
                        "x_ratio", "y_ratio", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "webbing_tension": {
                "type": "object",
                "properties": {
                    "kg_per_inch_specified": {"type": "number"},
                    "kg_per_inch_band": {
                        "type": "object",
                        "properties": {
                            "low": {"type": "number"},
                            "high": {"type": "number"},
                        },
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "weave_pattern": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "kg_per_inch_specified", "kg_per_inch_band",
                    "weave_pattern", "rationale",
                ],
                "additionalProperties": False,
            },
            "foam_cutting_tolerance": {
                "type": "object",
                "properties": {
                    "tolerance_mm": {"type": "number"},
                    "method": {"type": "string"},                   # "hot wire", "CNC bandsaw", "die-cut"
                    "rationale": {"type": "string"},
                },
                "required": ["tolerance_mm", "method", "rationale"],
                "additionalProperties": False,
            },
            "zipper_placement": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},                  # Z1, Z2
                        "applies_to": {"type": "string"},
                        "type": {"type": "string"},                 # ZIPPER_TYPES_IN_SCOPE
                        "length_mm": {"type": "number"},
                        "edge_offset_mm": {"type": "number"},       # how far from cushion edge
                        "orientation": {"type": "string"},          # "rear seam", "underside", "side"
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "key", "applies_to", "type", "length_mm",
                        "edge_offset_mm", "orientation", "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "stitch_density": {
                "type": "object",
                "properties": {
                    "stitches_per_inch_specified": {"type": "number"},
                    "stitches_per_inch_band": {
                        "type": "object",
                        "properties": {
                            "low": {"type": "number"},
                            "high": {"type": "number"},
                        },
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "thread_type": {"type": "string"},              # THREAD_TYPES_IN_SCOPE
                    "thread_weight_tex": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "stitches_per_inch_specified",
                    "stitches_per_inch_band",
                    "thread_type",
                    "thread_weight_tex",
                    "rationale",
                ],
                "additionalProperties": False,
            },
            "qc_checks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "lead_time": {
                "type": "object",
                "properties": {
                    "low_weeks": {"type": "number"},
                    "high_weeks": {"type": "number"},
                    "depends_on_frame_delivery": {"type": "string"},  # "yes" | "no"
                    "complexity": {"type": "string"},
                    "drivers": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "low_weeks", "high_weeks", "depends_on_frame_delivery",
                    "complexity", "drivers",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "applies_to",
            "frame_mounting_points",
            "webbing_tension",
            "foam_cutting_tolerance",
            "zipper_placement",
            "stitch_density",
            "qc_checks",
            "lead_time",
        ],
        "additionalProperties": False,
    }


def _assembly_notes_block_schema() -> dict[str, Any]:
    """BRD 3C — Assembly Notes block, lives under 'quality_assurance'."""
    return {
        "type": "object",
        "properties": {
            "assembly_sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer"},                # 1-based order
                        "title": {"type": "string"},                # short verb phrase
                        "detail": {"type": "string"},
                        "tools_required": {"type": "array", "items": {"type": "string"}},
                        "estimated_minutes": {"type": "number"},
                    },
                    "required": ["step", "title", "detail", "tools_required", "estimated_minutes"],
                    "additionalProperties": False,
                },
            },
            "hardware_installation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},                  # H1, H2 — match drawings
                        "fastener": {"type": "string"},             # "M5 × 30 bolt", "16ga staple"
                        "location": {"type": "string"},
                        "torque_nm": {"type": "number"},            # 0 if not critical
                        "critical": {"type": "string"},             # "yes" | "no"
                        "notes": {"type": "string"},
                    },
                    "required": ["key", "fastener", "location", "torque_nm", "critical", "notes"],
                    "additionalProperties": False,
                },
            },
            "quality_checkpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "test_type": {"type": "string"},            # QC_TEST_TYPES_IN_SCOPE
                        "method": {"type": "string"},               # how to test
                        "acceptance_criterion": {"type": "string"}, # pass condition
                    },
                    "required": ["test_type", "method", "acceptance_criterion"],
                    "additionalProperties": False,
                },
            },
            "final_inspection": {
                "type": "object",
                "properties": {
                    "checklist": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},          # e.g. "frame square ±2 mm"
                                "linked_qa_gate": {"type": "string"}, # one of qa_gate_keys_in_scope
                                "method": {"type": "string"},
                                "acceptance": {"type": "string"},
                            },
                            "required": ["item", "linked_qa_gate", "method", "acceptance"],
                            "additionalProperties": False,
                        },
                    },
                    "sign_off_role": {"type": "string"},              # "Foreman" / "QA Lead" / "Studio PM"
                    "rejection_handling": {"type": "string"},
                },
                "required": ["checklist", "sign_off_role", "rejection_handling"],
                "additionalProperties": False,
            },
            "packaging": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},                   # PACKAGING_METHODS_IN_SCOPE
                    "protection_layers": {                          # list of inner-protection items
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "outer_dimensions_mm": {
                        "type": "object",
                        "properties": {
                            "length": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                        "required": ["length", "width", "height"],
                        "additionalProperties": False,
                    },
                    "weight_kg_estimate": {"type": "number"},
                    "labelling": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "method", "protection_layers", "outer_dimensions_mm",
                    "weight_kg_estimate", "labelling", "rationale",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "assembly_sequence",
            "hardware_installation",
            "quality_checkpoints",
            "final_inspection",
            "packaging",
        ],
        "additionalProperties": False,
    }


MANUFACTURING_SPEC_SCHEMA: dict[str, Any] = {
    "name": "manufacturing_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "theme": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "city": {"type": "string"},
                    "city_price_index": {"type": "number"},
                },
                "required": ["project", "theme", "date_iso", "city", "city_price_index"],
                "additionalProperties": False,
            },
            "woodworking_notes": _woodworking_block_schema(),
            "metal_fabrication_notes": _metal_fabrication_block_schema(),
            "upholstery_assembly_notes": _upholstery_assembly_block_schema(),
            "quality_assurance": _assembly_notes_block_schema(),
            # Reserved for the next BRD bullet — loose-typed for now.
            "testing": {"type": "object"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header",
            "woodworking_notes",
            "metal_fabrication_notes",
            "upholstery_assembly_notes",
            "quality_assurance",
            "testing",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: ManufacturingSpecRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Theme: {req.theme}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Date (UTC ISO): {today}\n"
        f"- Sections requested: {', '.join(req.sections or ['woodworking_notes'])}\n\n"
        "Produce the manufacturing_spec JSON. Fill the header block, then the "
        "woodworking_notes, metal_fabrication_notes, upholstery_assembly_notes, AND "
        "quality_assurance (Assembly Notes — assembly sequence, hardware torques, QC "
        "checkpoints, final inspection, packaging) blocks. Leave testing as an EMPTY OBJECT "
        "for now (next BRD bullet will fill it). Cite real BRD numbers — never invent "
        "precision bands, joinery tolerances, weld testing rules, bending radii, "
        "powder-coat cure parameters, webbing tension, foam tolerance, stitch density, "
        "QA gate keys, packaging methods, lead times, or MOQ."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _within(value: float, band: tuple[float, float] | list[float]) -> bool:
    if not isinstance(band, (tuple, list)) or len(band) != 2:
        return True
    lo, hi = float(band[0]), float(band[1])
    return lo - 1e-6 <= float(value) <= hi + 1e-6


def _validate_metal_fabrication_block(
    block: dict[str, Any],
    *,
    metal_brd: dict[str, Any],
    bending_rule: dict[str, Any],
    powder_coat_spec: dict[str, Any],
    metal_lead_band: tuple | list,
    palette_hex: set[str],
    out: dict[str, list[Any]],
) -> None:
    """Grade the metal fabrication notes block against BRD constants."""

    if not block.get("applies_to"):
        # No metal parts — caller should still pass an empty list explicitly.
        out["metal_no_parts_declared"].append(True)
        return

    # Welding method.
    weld = block.get("welding_quality") or {}
    primary = (weld.get("primary_method") or "").strip()
    if primary not in WELDING_METHODS_IN_SCOPE:
        out["bad_welding_method"].append(primary or "<missing>")

    # Weld testing.
    wt = block.get("weld_testing") or {}
    lb = (wt.get("load_bearing") or "").lower()
    if lb not in LOAD_BEARING_FLAGS:
        out["bad_load_bearing_flag"].append(lb or "<missing>")
    methods = [(m or "").lower() for m in (wt.get("methods") or [])]
    bad_methods = [m for m in methods if m not in WELD_TESTING_METHODS_IN_SCOPE]
    if bad_methods:
        out["bad_weld_testing_methods"].extend(bad_methods)
    if "visual_inspection" not in methods:
        out["weld_testing_missing_visual"].append(True)
    if lb == "yes" and "x_ray_radiography" not in methods:
        out["load_bearing_missing_xray"].append(True)

    # Bending.
    bend = block.get("bending") or {}
    expected_rule = (bending_rule or {}).get("rule")
    if expected_rule and bend.get("rule") != expected_rule:
        out["bad_bending_rule"].append({
            "expected": expected_rule, "actual": bend.get("rule"),
        })
    t = bend.get("thickness_mm")
    rmin = bend.get("min_radius_mm")
    rspec = bend.get("specified_radius_mm")
    if t is not None:
        expected_min = float(t) * 2.5
        if rmin is None or abs(float(rmin) - expected_min) > 1e-6:
            out["bad_min_radius"].append({"thickness_mm": t, "expected": expected_min, "actual": rmin})
        if rspec is not None and float(rspec) < expected_min - 1e-6:
            out["specified_below_min_radius"].append({
                "thickness_mm": t, "min_required": expected_min, "specified": rspec,
            })

    # Tolerances.
    tol = block.get("tolerances_mm") or {}
    expected_struct = metal_brd.get("tolerance_structural_mm")
    expected_cosm = metal_brd.get("tolerance_cosmetic_mm")
    if expected_struct is not None and tol.get("structural") is not None:
        if abs(float(tol["structural"]) - float(expected_struct)) > 1e-6:
            out["bad_metal_tolerance"].append({
                "field": "structural", "expected_mm": expected_struct, "actual_mm": tol["structural"],
            })
    if expected_cosm is not None and tol.get("cosmetic") is not None:
        if abs(float(tol["cosmetic"]) - float(expected_cosm)) > 1e-6:
            out["bad_metal_tolerance"].append({
                "field": "cosmetic", "expected_mm": expected_cosm, "actual_mm": tol["cosmetic"],
            })

    # Powder coat.
    pc = block.get("powder_coat") or {}
    expected_thick = powder_coat_spec.get("thickness_microns")
    band = pc.get("thickness_microns_band") or {}
    if isinstance(expected_thick, tuple) and len(expected_thick) == 2:
        exp_lo, exp_hi = expected_thick
        if abs(float(band.get("low") or -1) - float(exp_lo)) > 1e-6 or abs(float(band.get("high") or -1) - float(exp_hi)) > 1e-6:
            out["bad_powder_coat_band"].append({
                "expected": [exp_lo, exp_hi],
                "actual": [band.get("low"), band.get("high")],
            })
        spec_thick = pc.get("thickness_microns_specified")
        if spec_thick is not None and not (float(exp_lo) - 1e-6 <= float(spec_thick) <= float(exp_hi) + 1e-6):
            out["powder_coat_specified_out_of_band"].append({
                "specified": spec_thick, "band": [exp_lo, exp_hi],
            })

    expected_cure_temp = powder_coat_spec.get("cure_temp_c")
    if expected_cure_temp is not None and pc.get("cure_temp_c") is not None:
        if abs(float(pc["cure_temp_c"]) - float(expected_cure_temp)) > 1e-6:
            out["bad_powder_coat_cure_temp"].append({
                "expected_c": expected_cure_temp, "actual_c": pc["cure_temp_c"],
            })
    cure_time_band = powder_coat_spec.get("cure_time_min")
    if isinstance(cure_time_band, tuple) and len(cure_time_band) == 2:
        ct = pc.get("cure_time_min")
        lo, hi = cure_time_band
        if ct is None or not (float(lo) - 1e-6 <= float(ct) <= float(hi) + 1e-6):
            out["bad_powder_coat_cure_time"].append({
                "specified_min": ct, "band_min": [lo, hi],
            })

    # Hex from palette (allow RAL/Pantone strings to bypass).
    hex_v = (pc.get("color_code") or "").strip()
    if hex_v and hex_v.startswith("#"):
        if palette_hex and hex_v.lower() not in palette_hex:
            out["bad_powder_coat_hex"].append(hex_v)

    # Lead time.
    lt = block.get("lead_time") or {}
    complexity = (lt.get("complexity") or "").lower()
    if complexity not in COMPLEXITY_LEVELS_IN_SCOPE:
        out["bad_metal_complexity"].append(complexity or "<missing>")
    if isinstance(metal_lead_band, (tuple, list)) and len(metal_lead_band) == 2:
        lo_b, hi_b = float(metal_lead_band[0]), float(metal_lead_band[1])
        slack_hi = hi_b * 1.20 if complexity == "highly_complex" else hi_b
        if lt.get("low_weeks") is not None and not (lo_b - 1e-6 <= float(lt["low_weeks"]) <= hi_b + 1e-6):
            out["out_of_metal_lead_band"].append({"side": "low", "value": lt["low_weeks"], "band": [lo_b, hi_b]})
        if lt.get("high_weeks") is not None and not (lo_b - 1e-6 <= float(lt["high_weeks"]) <= slack_hi + 1e-6):
            out["out_of_metal_lead_band"].append({
                "side": "high", "value": lt["high_weeks"], "band": [lo_b, slack_hi], "complexity": complexity,
            })


def _validate_upholstery_assembly_block(
    block: dict[str, Any],
    *,
    upholstery_brd: dict[str, Any],
    qc_checks_in_scope: set[str],
    upholstery_lead_band: tuple | list,
    out: dict[str, list[Any]],
) -> None:
    """Grade the upholstery assembly notes block against BRD constants."""

    if not block.get("applies_to"):
        out["upholstery_no_parts_declared"].append(True)
        return

    # Mounting points (case-insensitive method check).
    mount_methods_lower = {m.lower() for m in MOUNT_METHODS_IN_SCOPE}
    mounts = block.get("frame_mounting_points") or []
    bad_mount_methods = [
        m.get("method") for m in mounts if (m.get("method") or "").lower() not in mount_methods_lower
    ]
    if bad_mount_methods:
        out["bad_mount_methods"].extend(bad_mount_methods)
    bad_mount_ratios: list[str] = []
    for m in mounts:
        for axis in ("x_ratio", "y_ratio"):
            v = m.get(axis)
            if v is None or not (0.0 <= float(v) <= 1.0):
                bad_mount_ratios.append(f"{m.get('key')}.{axis}")
    if bad_mount_ratios:
        out["bad_mount_ratios"].extend(bad_mount_ratios)
    if mounts and len(mounts) < 2:
        out["too_few_mounts"].append({"count": len(mounts), "minimum": 2})

    # Webbing tension.
    web = block.get("webbing_tension") or {}
    expected_web_band = upholstery_brd.get("webbing_tension_kg_per_inch")
    band = web.get("kg_per_inch_band") or {}
    if isinstance(expected_web_band, tuple) and len(expected_web_band) == 2:
        exp_lo, exp_hi = expected_web_band
        if abs(float(band.get("low") or -1) - float(exp_lo)) > 1e-6 or abs(float(band.get("high") or -1) - float(exp_hi)) > 1e-6:
            out["bad_webbing_band"].append({
                "expected": [exp_lo, exp_hi],
                "actual": [band.get("low"), band.get("high")],
            })
        v = web.get("kg_per_inch_specified")
        if v is None or not (float(exp_lo) - 1e-6 <= float(v) <= float(exp_hi) + 1e-6):
            out["webbing_specified_out_of_band"].append({
                "specified": v, "band": [exp_lo, exp_hi],
            })

    # Foam cutting tolerance.
    foam_tol = block.get("foam_cutting_tolerance") or {}
    expected_foam_tol = upholstery_brd.get("foam_tolerance_mm")
    if expected_foam_tol is not None and foam_tol.get("tolerance_mm") is not None:
        if abs(float(foam_tol["tolerance_mm"]) - float(expected_foam_tol)) > 1e-6:
            out["bad_foam_tolerance"].append({
                "expected_mm": expected_foam_tol,
                "actual_mm": foam_tol["tolerance_mm"],
            })

    # Zipper placement (case-insensitive type check).
    zipper_types_lower = {z.lower() for z in ZIPPER_TYPES_IN_SCOPE}
    zips = block.get("zipper_placement") or []
    bad_zipper_types = [
        z.get("type") for z in zips if (z.get("type") or "").lower() not in zipper_types_lower
    ]
    if bad_zipper_types:
        out["bad_zipper_types"].extend(bad_zipper_types)
    bad_zipper_dims = [
        z.get("key") for z in zips
        if z.get("length_mm") is None or float(z.get("length_mm") or 0) <= 0
        or z.get("edge_offset_mm") is None or float(z.get("edge_offset_mm") or -1) < 0
    ]
    if bad_zipper_dims:
        out["bad_zipper_dimensions"].extend(bad_zipper_dims)

    # Stitch density.
    sd = block.get("stitch_density") or {}
    expected_stitch_band = upholstery_brd.get("stitch_density_per_inch")
    band = sd.get("stitches_per_inch_band") or {}
    if isinstance(expected_stitch_band, tuple) and len(expected_stitch_band) == 2:
        exp_lo, exp_hi = expected_stitch_band
        if abs(float(band.get("low") or -1) - float(exp_lo)) > 1e-6 or abs(float(band.get("high") or -1) - float(exp_hi)) > 1e-6:
            out["bad_stitch_band"].append({
                "expected": [exp_lo, exp_hi],
                "actual": [band.get("low"), band.get("high")],
            })
        v = sd.get("stitches_per_inch_specified")
        if v is None or not (float(exp_lo) - 1e-6 <= float(v) <= float(exp_hi) + 1e-6):
            out["stitch_specified_out_of_band"].append({
                "specified": v, "band": [exp_lo, exp_hi],
            })
    thread = (sd.get("thread_type") or "").lower()
    if thread and thread not in THREAD_TYPES_IN_SCOPE:
        out["bad_thread_type"].append(thread)
    tex = sd.get("thread_weight_tex")
    if tex is not None and not (10 <= float(tex) <= 200):
        out["bad_thread_weight"].append({"tex": tex, "expected_range": [10, 200]})

    # QC checks subset.
    bad_qc = [c for c in (block.get("qc_checks") or []) if c not in qc_checks_in_scope]
    if bad_qc:
        out["bad_uphol_qc_checks"].extend(bad_qc)

    # Lead time + complexity + frame-delivery dependency.
    lt = block.get("lead_time") or {}
    complexity = (lt.get("complexity") or "").lower()
    if complexity not in COMPLEXITY_LEVELS_IN_SCOPE:
        out["bad_uphol_complexity"].append(complexity or "<missing>")
    depends = (lt.get("depends_on_frame_delivery") or "").lower()
    if depends not in {"yes", "no"}:
        out["bad_frame_dependency_flag"].append(depends or "<missing>")
    if isinstance(upholstery_lead_band, (tuple, list)) and len(upholstery_lead_band) == 2:
        lo_b, hi_b = float(upholstery_lead_band[0]), float(upholstery_lead_band[1])
        slack_hi = hi_b * 1.20 if complexity == "highly_complex" else hi_b
        if lt.get("low_weeks") is not None and not (lo_b - 1e-6 <= float(lt["low_weeks"]) <= hi_b + 1e-6):
            out["out_of_uphol_lead_band"].append({
                "side": "low", "value": lt["low_weeks"], "band": [lo_b, hi_b],
            })
        if lt.get("high_weeks") is not None and not (lo_b - 1e-6 <= float(lt["high_weeks"]) <= slack_hi + 1e-6):
            out["out_of_uphol_lead_band"].append({
                "side": "high", "value": lt["high_weeks"], "band": [lo_b, slack_hi], "complexity": complexity,
            })


def _validate_assembly_notes_block(
    block: dict[str, Any],
    *,
    qa_gate_keys: set[str],
    out: dict[str, list[Any]],
) -> None:
    """Grade the BRD 3C Assembly Notes (quality_assurance) block."""

    # Assembly sequence — at least 4 steps, sequential numbering, positive durations.
    seq = block.get("assembly_sequence") or []
    if len(seq) < 4:
        out["too_few_assembly_steps"].append({"count": len(seq), "minimum": 4})
    expected_step = 1
    for s in seq:
        if s.get("step") != expected_step:
            out["bad_assembly_sequence"].append({
                "expected_step": expected_step, "actual_step": s.get("step"),
            })
        if s.get("estimated_minutes") is None or float(s.get("estimated_minutes") or 0) <= 0:
            out["bad_assembly_minutes"].append({
                "step": s.get("step"), "value": s.get("estimated_minutes"),
            })
        expected_step += 1

    # Hardware installation — torque must be > 0 when critical=yes, zero when no.
    for hw in block.get("hardware_installation") or []:
        crit = (hw.get("critical") or "").lower()
        if crit not in {"yes", "no"}:
            out["bad_hardware_critical_flag"].append(f"{hw.get('key')} -> {crit}")
            continue
        torque = hw.get("torque_nm")
        if crit == "yes" and (torque is None or float(torque) <= 0):
            out["bad_hardware_torque"].append({
                "key": hw.get("key"), "critical": "yes", "torque_nm": torque,
            })

    # Quality checkpoints — at least 3 entries, all in catalogue.
    qcs = block.get("quality_checkpoints") or []
    if len(qcs) < 3:
        out["too_few_quality_checkpoints"].append({"count": len(qcs), "minimum": 3})
    bad_qc_test_types = [
        q.get("test_type") for q in qcs
        if (q.get("test_type") or "").lower() not in {t.lower() for t in QC_TEST_TYPES_IN_SCOPE}
    ]
    if bad_qc_test_types:
        out["bad_qc_test_types"].extend(bad_qc_test_types)

    # Final inspection — at least 5 checklist items, every linked_qa_gate in catalogue.
    fi = block.get("final_inspection") or {}
    checklist = fi.get("checklist") or []
    if len(checklist) < 5:
        out["too_few_final_inspection_items"].append({"count": len(checklist), "minimum": 5})
    bad_linked_gates = [
        c.get("linked_qa_gate") for c in checklist
        if c.get("linked_qa_gate") not in qa_gate_keys
    ]
    if bad_linked_gates:
        out["bad_linked_qa_gates"].extend(bad_linked_gates)

    # Packaging.
    pkg = block.get("packaging") or {}
    method = (pkg.get("method") or "").lower()
    if method and method not in {m.lower() for m in PACKAGING_METHODS_IN_SCOPE}:
        out["bad_packaging_method"].append(method)
    bad_protection = [
        p for p in (pkg.get("protection_layers") or [])
        if p.lower() not in {x.lower() for x in PROTECTION_LAYERS_IN_SCOPE}
    ]
    if bad_protection:
        out["bad_protection_layers"].extend(bad_protection)
    dims = pkg.get("outer_dimensions_mm") or {}
    bad_dims: list[str] = []
    for axis in ("length", "width", "height"):
        v = dims.get(axis)
        if v is None or float(v) <= 0:
            bad_dims.append(axis)
    if bad_dims:
        out["bad_packaging_dimensions"].extend(bad_dims)
    weight = pkg.get("weight_kg_estimate")
    if weight is None or float(weight) <= 0:
        out["bad_packaging_weight"].append(weight)


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    block = spec.get("woodworking_notes") or {}
    brd = knowledge.get("manufacturing_brd", {}) or {}
    precision_bands = brd.get("precision_requirements_mm", {}) or {}
    tolerances = brd.get("tolerances_mm", {}) or {}
    woodwork_brd = brd.get("woodworking_brd_spec", {}) or {}
    lead_band = woodwork_brd.get("lead_time_weeks") or brd.get("lead_times_weeks", {}).get("woodworking_furniture")
    moq_floor = brd.get("moq_units", {}).get("woodworking_small_batch") or 1
    joinery_catalogue = knowledge.get("joinery_catalogue", {}) or {}
    finishes_catalogue = knowledge.get("finishes_catalogue", {}) or {}
    qa_gate_keys = set(knowledge.get("qa_gate_keys_in_scope", []))

    out: dict[str, list[Any]] = {
        "bad_precision_level": [],
        "precision_tolerance_mismatch": [],
        "bad_joinery": [],
        "joinery_tolerance_mismatch": [],
        "bad_global_tolerance": [],
        "bad_finishing_step": [],
        "bad_finish_system": [],
        "bad_qa_gate": [],
        "out_of_lead_band": [],
        "bad_complexity": [],
        "bad_moq": [],
        # Metal fabrication-specific buckets.
        "metal_no_parts_declared": [],
        "bad_welding_method": [],
        "bad_load_bearing_flag": [],
        "bad_weld_testing_methods": [],
        "weld_testing_missing_visual": [],
        "load_bearing_missing_xray": [],
        "bad_bending_rule": [],
        "bad_min_radius": [],
        "specified_below_min_radius": [],
        "bad_metal_tolerance": [],
        "bad_powder_coat_band": [],
        "powder_coat_specified_out_of_band": [],
        "bad_powder_coat_cure_temp": [],
        "bad_powder_coat_cure_time": [],
        "bad_powder_coat_hex": [],
        "bad_metal_complexity": [],
        "out_of_metal_lead_band": [],
        # Upholstery-assembly buckets.
        "upholstery_no_parts_declared": [],
        "bad_mount_methods": [],
        "bad_mount_ratios": [],
        "too_few_mounts": [],
        "bad_webbing_band": [],
        "webbing_specified_out_of_band": [],
        "bad_foam_tolerance": [],
        "bad_zipper_types": [],
        "bad_zipper_dimensions": [],
        "bad_stitch_band": [],
        "stitch_specified_out_of_band": [],
        "bad_thread_type": [],
        "bad_thread_weight": [],
        "bad_uphol_qc_checks": [],
        "bad_uphol_complexity": [],
        "bad_frame_dependency_flag": [],
        "out_of_uphol_lead_band": [],
        # Assembly notes / final QA buckets.
        "too_few_assembly_steps": [],
        "bad_assembly_sequence": [],
        "bad_assembly_minutes": [],
        "bad_hardware_critical_flag": [],
        "bad_hardware_torque": [],
        "too_few_quality_checkpoints": [],
        "bad_qc_test_types": [],
        "too_few_final_inspection_items": [],
        "bad_linked_qa_gates": [],
        "bad_packaging_method": [],
        "bad_protection_layers": [],
        "bad_packaging_dimensions": [],
        "bad_packaging_weight": [],
    }

    # Precision level + tolerance.
    pr = block.get("machine_precision_required") or {}
    level = (pr.get("level") or "").lower()
    if level not in PRECISION_LEVELS_IN_SCOPE:
        out["bad_precision_level"].append(level)
    expected_tol = None
    if level == "structural":
        expected_tol = precision_bands.get("structural_mm")
    elif level == "cosmetic":
        expected_tol = precision_bands.get("cosmetic_mm")
    elif level == "standard":
        expected_tol = tolerances.get("woodworking_standard")
    if expected_tol is not None and pr.get("tolerance_mm") is not None:
        if abs(float(pr["tolerance_mm"]) - float(expected_tol)) > 1e-6:
            out["precision_tolerance_mismatch"].append({
                "level": level, "expected_mm": expected_tol, "actual_mm": pr["tolerance_mm"],
            })

    # Joinery methods.
    for j in block.get("joinery_methods") or []:
        method = (j.get("method") or "").lower()
        if method not in JOINERY_KEYS_IN_SCOPE:
            out["bad_joinery"].append(method)
            continue
        expected = joinery_catalogue.get(method, {}).get("tolerance_mm")
        if expected is not None and j.get("tolerance_mm") is not None:
            if abs(float(j["tolerance_mm"]) - float(expected)) > 1e-6:
                out["joinery_tolerance_mismatch"].append({
                    "method": method, "expected_mm": expected, "actual_mm": j["tolerance_mm"],
                })

    # Joinery global tolerances bucket.
    jt = block.get("joinery_tolerances") or {}
    expected_struct = tolerances.get("structural")
    expected_assembly = tolerances.get("cosmetic")
    if expected_struct is not None and jt.get("structural_mm") is not None:
        if abs(float(jt["structural_mm"]) - float(expected_struct)) > 1e-6:
            out["bad_global_tolerance"].append({
                "field": "structural_mm", "expected_mm": expected_struct, "actual_mm": jt["structural_mm"],
            })
    if expected_assembly is not None and jt.get("assembly_mm") is not None:
        if abs(float(jt["assembly_mm"]) - float(expected_assembly)) > 1e-6:
            out["bad_global_tolerance"].append({
                "field": "assembly_mm", "expected_mm": expected_assembly, "actual_mm": jt["assembly_mm"],
            })

    # Finishing sequence steps.
    for s in block.get("finishing_sequence") or []:
        step = (s.get("step") or "").lower()
        if step not in FINISHING_STEPS_IN_SCOPE:
            out["bad_finishing_step"].append(step)

    # Finish system.
    fs = block.get("finish_system")
    if fs and fs not in finishes_catalogue:
        out["bad_finish_system"].append(fs)

    # QA gates.
    for g in block.get("quality_gates") or []:
        stage = g.get("stage")
        if stage not in qa_gate_keys:
            out["bad_qa_gate"].append(stage)

    # Lead time + complexity.
    lt = block.get("lead_time") or {}
    complexity = (lt.get("complexity") or "").lower()
    if complexity not in COMPLEXITY_LEVELS_IN_SCOPE:
        out["bad_complexity"].append(complexity)
    if isinstance(lead_band, (tuple, list)) and len(lead_band) == 2:
        # Allow up to +25% slack on the high end for highly_complex.
        lo_b, hi_b = float(lead_band[0]), float(lead_band[1])
        slack_hi = hi_b * 1.25 if complexity == "highly_complex" else hi_b
        if lt.get("low_weeks") is not None and not (lo_b - 1e-6 <= float(lt["low_weeks"]) <= hi_b + 1e-6):
            out["out_of_lead_band"].append({"side": "low", "value": lt["low_weeks"], "band": [lo_b, hi_b]})
        if lt.get("high_weeks") is not None and not (lo_b - 1e-6 <= float(lt["high_weeks"]) <= slack_hi + 1e-6):
            out["out_of_lead_band"].append({
                "side": "high", "value": lt["high_weeks"],
                "band": [lo_b, slack_hi], "complexity": complexity,
            })

    # MOQ.
    moq = block.get("moq") or {}
    if moq.get("units") is None or int(moq["units"]) < int(moq_floor):
        out["bad_moq"].append({"value": moq.get("units"), "floor": moq_floor})

    # ── Metal fabrication block ────────────────────────────────────────────
    metal_block = spec.get("metal_fabrication_notes") or {}
    metal_brd = brd.get("metal_fabrication_brd_spec", {}) or {}
    metal_lead_band = brd.get("lead_times_weeks", {}).get("metal_fabrication") or (6, 10)
    palette_hex = {c.lower() for c in (knowledge.get("theme_rule_pack") or {}).get("colour_palette", [])}
    if metal_block:
        _validate_metal_fabrication_block(
            metal_block,
            metal_brd=metal_brd,
            bending_rule=knowledge.get("bending_rule") or {},
            powder_coat_spec=knowledge.get("powder_coat_spec") or {},
            metal_lead_band=metal_lead_band,
            palette_hex=palette_hex,
            out=out,
        )

    # ── Upholstery assembly block ──────────────────────────────────────────
    upholstery_block = spec.get("upholstery_assembly_notes") or {}
    upholstery_brd = brd.get("upholstery_assembly_brd_spec", {}) or {}
    upholstery_lead_band = brd.get("lead_times_weeks", {}).get("upholstery_post_frame") or (3, 6)
    qc_checks_in_scope = set(upholstery_brd.get("qc_checks") or ())
    if upholstery_block:
        _validate_upholstery_assembly_block(
            upholstery_block,
            upholstery_brd=upholstery_brd,
            qc_checks_in_scope=qc_checks_in_scope,
            upholstery_lead_band=upholstery_lead_band,
            out=out,
        )

    # ── Assembly notes / quality_assurance block ───────────────────────────
    qa_block = spec.get("quality_assurance") or {}
    qa_gate_keys_set = set(knowledge.get("qa_gate_keys_in_scope", []))
    if qa_block:
        _validate_assembly_notes_block(qa_block, qa_gate_keys=qa_gate_keys_set, out=out)

    return {
        "precision_level_valid": not out["bad_precision_level"],
        "bad_precision_level": out["bad_precision_level"],
        "precision_tolerance_matches_band": not out["precision_tolerance_mismatch"],
        "precision_tolerance_mismatch": out["precision_tolerance_mismatch"],
        "joinery_methods_valid": not out["bad_joinery"],
        "bad_joinery_methods": out["bad_joinery"],
        "joinery_tolerances_match_catalogue": not out["joinery_tolerance_mismatch"],
        "joinery_tolerance_mismatch": out["joinery_tolerance_mismatch"],
        "global_tolerances_match_brd": not out["bad_global_tolerance"],
        "bad_global_tolerances": out["bad_global_tolerance"],
        "finishing_steps_in_catalogue": not out["bad_finishing_step"],
        "bad_finishing_steps": out["bad_finishing_step"],
        "finish_system_in_catalogue": not out["bad_finish_system"],
        "bad_finish_system": out["bad_finish_system"],
        "qa_gates_in_catalogue": not out["bad_qa_gate"],
        "bad_qa_gates": out["bad_qa_gate"],
        "lead_time_in_band": not out["out_of_lead_band"],
        "out_of_lead_band": out["out_of_lead_band"],
        "complexity_valid": not out["bad_complexity"],
        "bad_complexity": out["bad_complexity"],
        "moq_meets_floor": not out["bad_moq"],
        "bad_moq": out["bad_moq"],
        # Metal fabrication section.
        "metal_no_parts_declared": bool(out["metal_no_parts_declared"]),
        "welding_method_valid": not out["bad_welding_method"],
        "bad_welding_methods": out["bad_welding_method"],
        "load_bearing_flag_valid": not out["bad_load_bearing_flag"],
        "bad_load_bearing_flags": out["bad_load_bearing_flag"],
        "weld_testing_methods_valid": not out["bad_weld_testing_methods"],
        "bad_weld_testing_methods": out["bad_weld_testing_methods"],
        "weld_testing_includes_visual": not out["weld_testing_missing_visual"],
        "load_bearing_includes_xray": not out["load_bearing_missing_xray"],
        "bending_rule_matches_brd": not out["bad_bending_rule"],
        "bad_bending_rule": out["bad_bending_rule"],
        "min_radius_matches_2_5x_thickness": not out["bad_min_radius"],
        "bad_min_radius": out["bad_min_radius"],
        "specified_radius_above_min": not out["specified_below_min_radius"],
        "specified_below_min_radius": out["specified_below_min_radius"],
        "metal_tolerances_match_brd": not out["bad_metal_tolerance"],
        "bad_metal_tolerances": out["bad_metal_tolerance"],
        "powder_coat_band_matches_brd": not out["bad_powder_coat_band"],
        "bad_powder_coat_band": out["bad_powder_coat_band"],
        "powder_coat_specified_in_band": not out["powder_coat_specified_out_of_band"],
        "powder_coat_specified_out_of_band": out["powder_coat_specified_out_of_band"],
        "powder_coat_cure_temp_matches_brd": not out["bad_powder_coat_cure_temp"],
        "bad_powder_coat_cure_temp": out["bad_powder_coat_cure_temp"],
        "powder_coat_cure_time_in_band": not out["bad_powder_coat_cure_time"],
        "bad_powder_coat_cure_time": out["bad_powder_coat_cure_time"],
        "powder_coat_hex_in_palette": not out["bad_powder_coat_hex"],
        "bad_powder_coat_hex": out["bad_powder_coat_hex"],
        "metal_complexity_valid": not out["bad_metal_complexity"],
        "bad_metal_complexity": out["bad_metal_complexity"],
        "metal_lead_in_band": not out["out_of_metal_lead_band"],
        "out_of_metal_lead_band": out["out_of_metal_lead_band"],
        # Upholstery assembly section.
        "upholstery_no_parts_declared": bool(out["upholstery_no_parts_declared"]),
        "mount_methods_valid": not out["bad_mount_methods"],
        "bad_mount_methods": out["bad_mount_methods"],
        "mount_ratios_valid": not out["bad_mount_ratios"],
        "bad_mount_ratios": out["bad_mount_ratios"],
        "enough_mount_points": not out["too_few_mounts"],
        "too_few_mounts": out["too_few_mounts"],
        "webbing_band_matches_brd": not out["bad_webbing_band"],
        "bad_webbing_band": out["bad_webbing_band"],
        "webbing_specified_in_band": not out["webbing_specified_out_of_band"],
        "webbing_specified_out_of_band": out["webbing_specified_out_of_band"],
        "foam_tolerance_matches_brd": not out["bad_foam_tolerance"],
        "bad_foam_tolerance": out["bad_foam_tolerance"],
        "zipper_types_valid": not out["bad_zipper_types"],
        "bad_zipper_types": out["bad_zipper_types"],
        "zipper_dimensions_valid": not out["bad_zipper_dimensions"],
        "bad_zipper_dimensions": out["bad_zipper_dimensions"],
        "stitch_band_matches_brd": not out["bad_stitch_band"],
        "bad_stitch_band": out["bad_stitch_band"],
        "stitch_specified_in_band": not out["stitch_specified_out_of_band"],
        "stitch_specified_out_of_band": out["stitch_specified_out_of_band"],
        "thread_type_valid": not out["bad_thread_type"],
        "bad_thread_type": out["bad_thread_type"],
        "thread_weight_in_range": not out["bad_thread_weight"],
        "bad_thread_weight": out["bad_thread_weight"],
        "uphol_qc_checks_valid": not out["bad_uphol_qc_checks"],
        "bad_uphol_qc_checks": out["bad_uphol_qc_checks"],
        "uphol_complexity_valid": not out["bad_uphol_complexity"],
        "bad_uphol_complexity": out["bad_uphol_complexity"],
        "frame_dependency_flag_valid": not out["bad_frame_dependency_flag"],
        "bad_frame_dependency_flag": out["bad_frame_dependency_flag"],
        "uphol_lead_in_band": not out["out_of_uphol_lead_band"],
        "out_of_uphol_lead_band": out["out_of_uphol_lead_band"],
        # Assembly notes / final QA section.
        "assembly_steps_meet_minimum": not out["too_few_assembly_steps"],
        "too_few_assembly_steps": out["too_few_assembly_steps"],
        "assembly_sequence_numbered_correctly": not out["bad_assembly_sequence"],
        "bad_assembly_sequence": out["bad_assembly_sequence"],
        "assembly_minutes_positive": not out["bad_assembly_minutes"],
        "bad_assembly_minutes": out["bad_assembly_minutes"],
        "hardware_critical_flags_valid": not out["bad_hardware_critical_flag"],
        "bad_hardware_critical_flags": out["bad_hardware_critical_flag"],
        "hardware_torque_consistent": not out["bad_hardware_torque"],
        "bad_hardware_torque": out["bad_hardware_torque"],
        "quality_checkpoints_meet_minimum": not out["too_few_quality_checkpoints"],
        "too_few_quality_checkpoints": out["too_few_quality_checkpoints"],
        "qc_test_types_valid": not out["bad_qc_test_types"],
        "bad_qc_test_types": out["bad_qc_test_types"],
        "final_inspection_items_meet_minimum": not out["too_few_final_inspection_items"],
        "too_few_final_inspection_items": out["too_few_final_inspection_items"],
        "linked_qa_gates_valid": not out["bad_linked_qa_gates"],
        "bad_linked_qa_gates": out["bad_linked_qa_gates"],
        "packaging_method_valid": not out["bad_packaging_method"],
        "bad_packaging_method": out["bad_packaging_method"],
        "protection_layers_valid": not out["bad_protection_layers"],
        "bad_protection_layers": out["bad_protection_layers"],
        "packaging_dimensions_valid": not out["bad_packaging_dimensions"],
        "bad_packaging_dimensions": out["bad_packaging_dimensions"],
        "packaging_weight_valid": not out["bad_packaging_weight"],
        "bad_packaging_weight": out["bad_packaging_weight"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class ManufacturingSpecError(RuntimeError):
    """Raised when the LLM manufacturing-spec stage cannot produce a grounded sheet."""


async def generate_manufacturing_spec(req: ManufacturingSpecRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ManufacturingSpecError(
            "OpenAI API key is not configured. The manufacturing-spec stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_manufacturing_spec_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise ManufacturingSpecError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the spec."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": MANUFACTURING_SPEC_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": MANUFACTURING_SPEC_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for manufacturing spec")
        raise ManufacturingSpecError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManufacturingSpecError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "manufacturing_spec",
        "name": "Manufacturing Specification",
        "model": settings.openai_model,
        "theme": req.theme,
        "city": req.city or None,
        "knowledge": knowledge,
        "manufacturing_spec": spec,
        "validation": validation,
    }
