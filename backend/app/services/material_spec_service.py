"""LLM-driven Material Specification Sheet service (BRD Layer 3B).

Authors a real practice-grade material spec sheet — the page production
reads to know exactly which species, grade, finish, colour, supplier,
lead time, and cost belongs in each material slot of the design.

Pipeline contract — same as every other LLM service in the project:

    INPUT (theme + parametric_spec + project metadata + region)
      → INJECT  (theme palette + BRD wood/metal/upholstery envelopes +
                 regional availability + price index + lead-time helpers)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (palette membership, grade in catalogue, finish in palette,
                   lead time in BRD band, cost in BRD band, region availability)
      → OUTPUT  (material_spec JSON conforming to the BRD template)

This module ships the *primary structure* block per BRD 3B. Subsequent
BRD bullets (secondary materials, hardware, upholstery, finishing,
total notes) extend the same `material_spec_sheet` schema so a single
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


# ── Request schema ──────────────────────────────────────────────────────────


class MaterialSpecRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    project_name: str = Field(default="KATHA Project", max_length=200)
    parametric_spec: dict[str, Any] | None = None
    city: str = Field(default="", max_length=80)
    sections: list[str] = Field(
        default_factory=lambda: [
            "primary_structure", "secondary_materials", "hardware",
            "upholstery", "finishing", "cost_summary",
        ],
        description=(
            "Sections to include. Implemented: 'primary_structure', 'secondary_materials', "
            "'hardware', 'upholstery', 'finishing', and the 'cost_summary' rollup."
        ),
    )


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_material_spec_knowledge(req: MaterialSpecRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    palette = pack.get("material_palette", {})
    primary_candidates = palette.get("primary", []) or []
    secondary_candidates = palette.get("secondary", []) or []

    # Wood candidate envelopes for any palette species we know.
    wood_envelopes = {
        sp: dict(materials.WOOD[sp])
        for sp in (primary_candidates + secondary_candidates)
        if sp in materials.WOOD
    }
    metal_envelopes = {
        sp: dict(materials.METALS[sp])
        for sp in (primary_candidates + secondary_candidates)
        if sp in materials.METALS
    }

    # Regional availability for every candidate the LLM (and hardware section)
    # may pick from — primary + secondary + accent + upholstery.
    accent_candidates = palette.get("accent", []) or []
    upholstery_candidates = palette.get("upholstery", []) or []
    availability = regional_materials.availability_report(
        primary_candidates + secondary_candidates + accent_candidates + upholstery_candidates,
        req.city or None,
    )

    parametric_summary = {
        "primary_species": (req.parametric_spec or {}).get("wood_spec", {}).get("primary_species"),
        "secondary_species": (req.parametric_spec or {}).get("wood_spec", {}).get("secondary_species"),
        "finish": (req.parametric_spec or {}).get("wood_spec", {}).get("finish"),
        "hardware_material": (req.parametric_spec or {}).get("hardware_spec", {}).get("material"),
    }

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "material_palette": palette,
            "colour_palette": pack.get("colour_palette", []),
            "colour_strategy": pack.get("colour_strategy"),
            "hardware": pack.get("hardware", {}),
            "material_pattern": pack.get("material_pattern", {}),
            "signature_moves": pack.get("signature_moves", []),
        },
        "parametric_summary": parametric_summary,
        "wood_envelopes": wood_envelopes,
        "metal_envelopes": metal_envelopes,
        "wood_brd": {
            "ranges": materials.WOOD_BRD_RANGES,
            "finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        },
        "metal_brd": {
            "specs": materials.METALS_BRD_SPECS,
            "cost_inr_kg": materials.METALS_BRD_COST_INR_KG,
            "finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
            "fabrication": list(materials.METALS_BRD_FABRICATION),
        },
        "upholstery_catalogue": {
            name: dict(spec) for name, spec in materials.UPHOLSTERY.items()
        },
        "upholstery_brd": {
            "leather": dict(materials.UPHOLSTERY_LEATHER_BRD_SPEC),
            "fabric": dict(materials.UPHOLSTERY_FABRIC_BRD_SPEC),
            "durability": dict(materials.UPHOLSTERY_DURABILITY_BRD),
            "colourfastness_min_of_5": materials.UPHOLSTERY_COLOURFASTNESS_MIN,
        },
        "foam_catalogue": {
            name: dict(spec) for name, spec in materials.FOAM.items()
        },
        "foam_brd": dict(materials.FOAM_BRD_SPEC),
        "upholstery_assembly_brd": dict(manufacturing.UPHOLSTERY_ASSEMBLY_BRD_SPEC),
        "finishes_catalogue": {
            name: dict(spec) for name, spec in materials.FINISHES.items()
        },
        "wood_finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        "metal_finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
        "waste_factor_pct_band": list(costing.WASTE_FACTOR_PCT),
        "regional_availability": availability,
        "city_price_index": regional_materials.price_index_for_city(req.city or None),
        "city": req.city or None,
        "sections_requested": list(req.sections or ["primary_structure"]),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


MATERIAL_SPEC_SYSTEM_PROMPT = """You are a senior procurement-aware architect preparing the *Material Specification Sheet* for a project. You translate the design's theme + parametric spec into row-by-row material decisions a workshop / supplier can act on.

Read the [KNOWLEDGE] block — theme palette, BRD wood + metal envelopes, parametric spec (primary species + finish), regional availability + city price index, candidate per-species envelopes — and produce a structured material_spec_sheet JSON.

Cover ALL BRD 3B blocks: PRIMARY STRUCTURE, SECONDARY MATERIALS, HARDWARE, UPHOLSTERY, FINISHING, plus the COST SUMMARY rollup at the bottom.

Hard rules per row in primary_structure or secondary_materials:
- For primary_structure rows: material MUST be in theme.material_palette.primary (or .secondary if a primary species doesn't apply to that slot).
- For secondary_materials rows: material MUST be in theme.material_palette.secondary or .accent (or .primary as a complementary face material when justified). Use this section for accent metals, glass, stone trims, panel substrates — anything that complements but doesn't carry the structure.
- grade_or_type MUST be a recognised commercial sub-grade for that species (e.g. for walnut: "FAS European" / "Select & Better Indian" / "Veneer-grade plywood core"; for steel: "Fe 250" / "Fe 500"; for brass: "Solid C36000"). Cite a specific grade — never just the species name.
- finish MUST be in wood_brd.finish_palette OR metal_brd.finish_palette (whichever family matches).
- color_code MUST be a hex value drawn from theme.colour_palette.
- supplier_recommendation: name 2–3 plausible vendor categories ("BRG Group / Greenply / Indian Plywood Manufacturers Association"); prefer locally-available where availability lists the city.
- lead_time_weeks MUST fall inside the species' candidate envelope (wood_envelopes[species].lead_time_weeks); if the material is in regional_availability.requires_transport, add the BRD remote_lead_time_adder_weeks band.
- cost_inr_per_unit + unit:
    * wood: pick from wood_envelopes[species].cost_inr_kg, multiply by city_price_index, keep unit = "kg" (or "m²" with sheet-stock conversion if you cite it).
    * metal: pick from metal_envelopes[species].cost_inr_kg × city_price_index, unit = "kg".
- Provide a one-line rationale per row tying the choice back to a theme signature_move or material_pattern note.
- The header block (project, theme, date) MUST be filled — date is current UTC date in ISO format (YYYY-MM-DD).
- Studio voice — short, decisive, no marketing prose.

Hard rules per row in hardware:
- key: short identifier (H1, H2, ...) — match the Elevation / Section drawing callouts when those exist.
- item: human-readable name ("Brass leg cap", "Steel L-bracket", "Concealed hinge 35 mm").
- hardware_type: one of knob | handle | hinge | bracket | leg_cap | screw | dowel | drawer_slide | lock | fastener.
- specification.dimensions_mm: free-form but specific (Ø22 × 18 H, 50 × 50 × 3 t, etc.).
- specification.material: solid brass / mild steel / stainless steel 304 / aluminium 6061 — use METALS catalogue keys where possible.
- specification.finish: from metal_finish_palette (powder coat / anodize / polished / brushed) — match theme.hardware.finish.
- quantity: derive from the parametric_summary (chair → 4 legs → 4 leg caps; cabinet door → 2 hinges, 1 pull). Never report 0.
- unit: 'pcs' unless the item is sold by length (then 'm') or weight ('kg').
- supplier_recommendation: 2–3 plausible vendor categories. For brass, note Moradabad as the hub if not the project city.
- cost_inr_per_unit: derive from metal_envelopes (mild_steel 60–90, brass 700–950 ₹/kg) by estimating mass × scaled rate, OR pick a plausible per-piece band when the catalogue is sparse. Apply city_price_index. Cite the basis in rationale.
- cost_inr_total: cost_inr_per_unit × quantity (low × low, high × high).
- lead_time_weeks: pull from the species envelope or default to 2–4 for in-stock; add remote_lead_time_adder_weeks when requires_transport.
- regional_status: locally_available / requires_transport / unknown — cross-check against regional_availability.
- Hardware that the theme says is "hidden / plinth-integrated" should still appear here (concealed hinges, hidden cleats), but the rationale must call out invisibility.

Hard rules per row in upholstery (only when the piece has cushioning / soft surfaces):
- key: short identifier (U1, U2, ...) — match drawing callouts.
- slot: where it sits ("seat cushion", "back cushion", "armrest pad", "headrest").
- cover.category MUST be one of: leather | fabric.
- cover.subtype MUST be a key in upholstery_catalogue (leather_genuine_grade_A/B/C/D, fabric_cotton, fabric_linen, fabric_wool_blend, fabric_synthetic_blend, fabric_performance_poly).
- cover.grade for leather MUST be one of A | B | C | D; for fabric, use a sub-grade descriptor (e.g. "performance" or "blend-class-1").
- cover.thickness_mm — leather only — MUST be in BRD band 1.2–1.5 (upholstery_brd.leather.thickness_mm); fabric uses 0 here and reports weight_gsm instead.
- cover.weight_gsm — fabric only — typical 250–450 gsm; leather uses 0.
- cover.durability_rubs_k MUST be in BRD 15–100 (upholstery_brd.durability.rubs_range_k); for commercial use ≥ upholstery_brd.durability.commercial_min_k (30).
- cover.colour_fastness_of_5 MUST be ≥ upholstery_brd.colourfastness_min_of_5 (4).
- cover.color_code MUST be in theme.colour_palette.
- backing.type MUST be one of: jute | muslin | scrim | polyester | cotton_canvas.
- foam.grade MUST be a key in foam_catalogue (HD36 / HR40 / memory_foam). Cite real density_kg_m3 from foam_catalogue (commercial reality), not the BRD-recorded 180 number — flag the BRD discrepancy in rationale if asked.
- foam.thickness_mm respects upholstery_assembly_brd.foam_tolerance_mm (±5 mm) at production; spec the nominal target.
- foam.filling_weight_kg_per_piece = density_kg_m3 × area_m2_per_piece × thickness_mm/1000.
- area_m2_per_piece > 0.
- cost_inr_per_m2 MUST sit inside the BRD band of the chosen subtype (upholstery_catalogue[subtype].cost_inr_m2) × city_price_index.
- cost_inr_total = cost_inr_per_m2 × area_m2_per_piece (low × low, high × high).

Hard rules per row in finishing:
- key: F1, F2, ... — sequence over the project.
- applies_to: name the slot it finishes ("primary frame", "leg cap", "upholstered seat", "metal accent").
- preparation.sanding_grits: list integers in ascending order (e.g. [120, 180, 240]); the highest grit is the final finish-prep pass.
- preparation.primer_type: from PU primer / shellac / sanding sealer / etch primer / epoxy primer / 'none' (use 'none' only when the top coat system is wax_oil and explicitly states no primer).
- base_coat.color_code MUST be in theme.colour_palette.
- top_coat.system MUST be a key in finishes_catalogue (lacquer_pu / melamine / wax_oil / powder_coat / anodise).
- top_coat.thickness_microns MUST sit inside finishes_catalogue[system].thickness_microns band.
- top_coat.coats MUST sit inside finishes_catalogue[system].coats band.
- top_coat.cure_temp_c + cure_time_min: only meaningful for powder_coat (200 °C, 10–15 min per BRD); for liquid finishes, set cure_temp_c to ambient room temperature (~25) and cure_time_min to manufacturer's flash-off (typically 30–120 min). State this in rationale.
- top_coat.sheen MUST be one of matte / satin / gloss.
- colour_fastness.uv_rating_of_8 MUST be ≥ 6 for indoor furniture, ≥ 7 for window-adjacent / outdoor pieces (ISO 105-B02 blue-wool 1–8 scale).
- area_m2 > 0; cost_inr_per_m2 MUST sit inside finishes_catalogue[system].cost_inr_m2 × city_price_index; cost_inr_total = cost_inr_per_m2 × area_m2 (1% wiggle).

Hard rules for cost_summary:
- by_section_inr.<section>.{low, high} = sum of every row's cost_inr_total in that section. Hardware and upholstery rows have explicit cost_inr_total; primary/secondary rows DO NOT report total per-row (they report cost_inr_per_unit × unit), so estimate primary/secondary contributions from a representative usage and STATE the assumption in notes.
- total_material_cost_inr.{low, high} = sum across all five by_section_inr entries.
- waste_factor_pct: pick a single number inside the BRD band waste_factor_pct_band (10–15). Default 12.5 if no signal.
- adjusted_material_cost_inr.{low, high} = total_material_cost_inr × (1 + waste_factor_pct/100); allow 0.5% rounding wiggle.
- currency = "INR".
- notes: short paragraph stating any assumptions used to estimate primary/secondary totals.

Do not invent suppliers with phone numbers or pretend addresses; vendor categories or known industry names only."""


# Reusable row shape — every BRD spec section uses the same seven fields
# (BRD 3B template). Duplicated rather than $ref-ed so the strict schema
# stays self-contained for the OpenAI structured-output validator.
def _spec_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "slot": {"type": "string"},                 # e.g. "frame", "leg cap", "trim"
            "material": {"type": "string"},              # species / alloy / fabric
            "grade_or_type": {"type": "string"},         # commercial sub-grade
            "finish": {"type": "string"},                # finish from BRD palette
            "color_code": {"type": "string"},            # hex from theme palette
            "supplier_recommendation": {"type": "string"},
            "lead_time_weeks": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "cost_inr_per_unit": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "unit": {"type": "string"},
            "regional_status": {"type": "string"},       # locally_available / requires_transport / unknown
            "rationale": {"type": "string"},
        },
        "required": [
            "slot", "material", "grade_or_type", "finish", "color_code",
            "supplier_recommendation", "lead_time_weeks", "cost_inr_per_unit",
            "unit", "regional_status", "rationale",
        ],
        "additionalProperties": False,
    }


# BRD 3B Hardware row — different shape (item + spec + quantity + supplier + cost)
# than the general material row. Kept as a dedicated schema so the LLM can't
# confuse a hardware item with a material slot.
def _hardware_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},                       # e.g. H1, H2 — same convention as drawing callouts
            "item": {"type": "string"},                      # "Brass leg cap", "Steel L-bracket"
            "hardware_type": {"type": "string"},             # knob | handle | hinge | bracket | leg_cap | screw | dowel
            "specification": {                               # BRD: dimensions + material + finish
                "type": "object",
                "properties": {
                    "dimensions_mm": {"type": "string"},     # free-form, e.g. "Ø22 × 18 H"
                    "material": {"type": "string"},          # alloy / metal name
                    "finish": {"type": "string"},            # from metal_finish_palette
                },
                "required": ["dimensions_mm", "material", "finish"],
                "additionalProperties": False,
            },
            "quantity": {"type": "integer"},                  # auto-calculated per piece program
            "unit": {"type": "string"},                       # "pcs"
            "supplier_recommendation": {"type": "string"},
            "cost_inr_per_unit": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "cost_inr_total": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "lead_time_weeks": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "regional_status": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "item", "hardware_type", "specification",
            "quantity", "unit", "supplier_recommendation",
            "cost_inr_per_unit", "cost_inr_total",
            "lead_time_weeks", "regional_status", "rationale",
        ],
        "additionalProperties": False,
    }


# BRD 3B Upholstery row — seven fields per BRD template:
#   leather/fabric (type, color, grade), density/weight, durability rating
#   (rubs), backing (jute/muslin), foam density (HD36 etc), filling weight
#   per piece, cost ₹/m².
def _upholstery_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},                       # U1, U2 — match drawing callouts
            "slot": {"type": "string"},                      # "seat cushion", "back cushion", "armrest pad"
            "cover": {                                        # leather / fabric line
                "type": "object",
                "properties": {
                    "category": {"type": "string"},          # "leather" | "fabric"
                    "subtype": {"type": "string"},           # leather_genuine_grade_A / fabric_wool_blend / etc
                    "grade": {"type": "string"},             # "A" | "B" | "C" | "D" | "performance" | etc
                    "color": {"type": "string"},             # human-readable
                    "color_code": {"type": "string"},        # hex from theme palette
                    "thickness_mm": {"type": "number"},      # leather only — 1.2-1.5
                    "weight_gsm": {"type": "number"},        # fabric only — typical 250-450
                    "durability_rubs_k": {"type": "number"}, # Martindale x1000 — 15-100
                    "colour_fastness_of_5": {"type": "number"},
                },
                "required": [
                    "category", "subtype", "grade", "color", "color_code",
                    "thickness_mm", "weight_gsm",
                    "durability_rubs_k", "colour_fastness_of_5",
                ],
                "additionalProperties": False,
            },
            "backing": {                                      # jute / muslin / scrim / polyester
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "weight_gsm": {"type": "number"},
                },
                "required": ["type", "weight_gsm"],
                "additionalProperties": False,
            },
            "foam": {                                         # HD36 / HR40 / memory_foam
                "type": "object",
                "properties": {
                    "grade": {"type": "string"},
                    "density_kg_m3": {"type": "number"},
                    "thickness_mm": {"type": "number"},
                    "filling_weight_kg_per_piece": {"type": "number"},
                },
                "required": [
                    "grade", "density_kg_m3", "thickness_mm",
                    "filling_weight_kg_per_piece",
                ],
                "additionalProperties": False,
            },
            "area_m2_per_piece": {"type": "number"},
            "cost_inr_per_m2": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "cost_inr_total": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "supplier_recommendation": {"type": "string"},
            "lead_time_weeks": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "regional_status": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "slot", "cover", "backing", "foam",
            "area_m2_per_piece", "cost_inr_per_m2", "cost_inr_total",
            "supplier_recommendation", "lead_time_weeks",
            "regional_status", "rationale",
        ],
        "additionalProperties": False,
    }


# BRD 3B Finishing row — five fields per BRD template:
#   preparation (sanding grits, primer), base coat (type, color),
#   top coat (lacquer/varnish/wax — thickness), color fastness (UV rating),
#   cost ₹.
def _finishing_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},                       # F1, F2 — sequence
            "applies_to": {"type": "string"},                # "primary frame", "leg cap", etc.
            "preparation": {
                "type": "object",
                "properties": {
                    "sanding_grits": {"type": "array", "items": {"type": "integer"}},
                    "primer_type": {"type": "string"},
                    "primer_coats": {"type": "integer"},
                },
                "required": ["sanding_grits", "primer_type", "primer_coats"],
                "additionalProperties": False,
            },
            "base_coat": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},              # stain / dye / sealer
                    "color": {"type": "string"},
                    "color_code": {"type": "string"},        # hex from theme palette
                    "coats": {"type": "integer"},
                },
                "required": ["type", "color", "color_code", "coats"],
                "additionalProperties": False,
            },
            "top_coat": {
                "type": "object",
                "properties": {
                    "system": {"type": "string"},            # FINISHES key (lacquer_pu / wax_oil / melamine / powder_coat / anodise)
                    "sheen": {"type": "string"},             # matte / satin / gloss
                    "thickness_microns": {"type": "number"},
                    "coats": {"type": "integer"},
                    "cure_temp_c": {"type": "number"},
                    "cure_time_min": {"type": "number"},
                },
                "required": [
                    "system", "sheen", "thickness_microns",
                    "coats", "cure_temp_c", "cure_time_min",
                ],
                "additionalProperties": False,
            },
            "colour_fastness": {                              # BRD: UV stability rating
                "type": "object",
                "properties": {
                    "uv_rating_of_8": {"type": "number"},    # ISO 105-B02 blue-wool 1-8
                    "expected_indoor_life_years": {"type": "number"},
                },
                "required": ["uv_rating_of_8", "expected_indoor_life_years"],
                "additionalProperties": False,
            },
            "area_m2": {"type": "number"},
            "cost_inr_per_m2": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "cost_inr_total": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "supplier_recommendation": {"type": "string"},
            "lead_time_weeks": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "applies_to", "preparation", "base_coat", "top_coat",
            "colour_fastness", "area_m2", "cost_inr_per_m2", "cost_inr_total",
            "supplier_recommendation", "lead_time_weeks", "rationale",
        ],
        "additionalProperties": False,
    }


# Cost rollup — BRD footer.
def _cost_summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "total_material_cost_inr": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "waste_factor_pct": {"type": "number"},                  # picked from BRD 10-15 band
            "adjusted_material_cost_inr": {
                "type": "object",
                "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                "required": ["low", "high"],
                "additionalProperties": False,
            },
            "by_section_inr": {
                "type": "object",
                "properties": {
                    "primary_structure": {
                        "type": "object",
                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "secondary_materials": {
                        "type": "object",
                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "hardware": {
                        "type": "object",
                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "upholstery": {
                        "type": "object",
                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                    "finishing": {
                        "type": "object",
                        "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                        "required": ["low", "high"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "primary_structure", "secondary_materials",
                    "hardware", "upholstery", "finishing",
                ],
                "additionalProperties": False,
            },
            "currency": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": [
            "total_material_cost_inr", "waste_factor_pct",
            "adjusted_material_cost_inr", "by_section_inr",
            "currency", "notes",
        ],
        "additionalProperties": False,
    }


TOPCOAT_SYSTEMS_IN_SCOPE = (
    "lacquer_pu", "melamine", "wax_oil", "powder_coat", "anodise",
)
TOPCOAT_SHEEN_IN_SCOPE = ("matte", "satin", "gloss")
PRIMER_TYPES_IN_SCOPE = ("PU primer", "shellac", "sanding sealer", "etch primer", "epoxy primer", "none")


COVER_CATEGORIES_IN_SCOPE = ("leather", "fabric")
LEATHER_GRADES_IN_SCOPE = ("A", "B", "C", "D")
BACKING_TYPES_IN_SCOPE = ("jute", "muslin", "scrim", "polyester", "cotton_canvas")


HARDWARE_TYPES_IN_SCOPE = (
    "knob", "handle", "hinge", "bracket", "leg_cap",
    "screw", "dowel", "drawer_slide", "lock", "fastener",
)


MATERIAL_SPEC_SCHEMA: dict[str, Any] = {
    "name": "material_spec_sheet",
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
            "primary_structure": {"type": "array", "items": _spec_row_schema()},
            "secondary_materials": {"type": "array", "items": _spec_row_schema()},
            "hardware": {"type": "array", "items": _hardware_row_schema()},
            "upholstery": {"type": "array", "items": _upholstery_row_schema()},
            "finishing": {"type": "array", "items": _finishing_row_schema()},
            "cost_summary": _cost_summary_schema(),
            "total_notes": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header",
            "primary_structure",
            "secondary_materials",
            "hardware",
            "upholstery",
            "finishing",
            "cost_summary",
            "total_notes",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: MaterialSpecRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Theme: {req.theme}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Date (UTC ISO): {today}\n"
        f"- Sections requested: {', '.join(req.sections or ['primary_structure'])}\n\n"
        "Produce the material_spec_sheet JSON. Fill the header block, then write:\n"
        "  • primary_structure rows (one per structural slot — frame, leg, apron, etc.).\n"
        "  • secondary_materials rows (accent metals, glass, panel substrates, stone trims, "
        "decorative faces — anything that complements but does not carry the structure).\n"
        "  • hardware rows (every visible AND concealed hardware item — leg caps, brackets, "
        "hinges, pulls, fasteners). Use the dedicated hardware row shape: key + item + "
        "hardware_type + specification {dimensions_mm, material, finish} + quantity + unit + "
        "supplier_recommendation + cost_inr_per_unit + cost_inr_total + lead_time_weeks + "
        "regional_status + rationale.\n"
        "  • upholstery rows (only when the piece has cushioning / soft surfaces). Use the "
        "dedicated upholstery row shape: key + slot + cover {category, subtype, grade, color, "
        "color_code, thickness_mm, weight_gsm, durability_rubs_k, colour_fastness_of_5} + "
        "backing {type, weight_gsm} + foam {grade, density_kg_m3, thickness_mm, "
        "filling_weight_kg_per_piece} + area_m2_per_piece + cost_inr_per_m2 + cost_inr_total "
        "+ supplier_recommendation + lead_time_weeks + regional_status + rationale.\n"
        "  • finishing rows (one per surface family that needs a finishing schedule). Use the "
        "dedicated finishing row shape: key + applies_to + preparation {sanding_grits, "
        "primer_type, primer_coats} + base_coat {type, color, color_code, coats} + top_coat "
        "{system, sheen, thickness_microns, coats, cure_temp_c, cure_time_min} + "
        "colour_fastness {uv_rating_of_8, expected_indoor_life_years} + area_m2 + "
        "cost_inr_per_m2 + cost_inr_total + supplier_recommendation + lead_time_weeks + "
        "rationale.\n"
        "  • cost_summary footer: total_material_cost_inr (sum of every row's cost_inr_total "
        "across all five sections, per the by_section_inr breakdown) + waste_factor_pct (pick "
        "12.5 default; range 10–15 from BRD) + adjusted_material_cost_inr (= total × (1 + "
        "waste/100)) + currency + a one-line notes paragraph stating any assumptions used to "
        "estimate primary/secondary contributions.\n"
        "Each material row uses the seven BRD fields. Cite real BRD numbers for lead time + "
        "cost; if a species isn't in the BRD wood_envelopes, fall back to the wood_brd.ranges "
        "band and state the assumption."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _within(value: float, band: tuple[float, float]) -> bool:
    if not isinstance(band, tuple) or len(band) != 2:
        return True
    lo, hi = float(band[0]), float(band[1])
    return lo - 1e-6 <= float(value) <= hi + 1e-6


def _validate_row(
    row: dict[str, Any],
    *,
    section: str,
    palette_pool: set[str],
    palette_hex: set[str],
    wood_finishes: set[str],
    metal_finishes: set[str],
    wood_envelopes: dict[str, Any],
    metal_envelopes: dict[str, Any],
    locally: set[str],
    remote: set[str],
    price_index: float,
    out: dict[str, list[Any]],
) -> None:
    """Grade a single row and accumulate findings into `out` (mutated)."""
    mat_key = (row.get("material") or "").lower().replace(" ", "_").replace("-", "_")
    slot_label = f"{section}:{row.get('slot')}"

    if palette_pool and mat_key not in palette_pool and not any(p in mat_key for p in palette_pool):
        out["bad_palette"].append(f"{slot_label} -> {row.get('material')}")

    hex_v = (row.get("color_code") or "").lower()
    if palette_hex and hex_v and hex_v not in palette_hex:
        out["bad_hex"].append(f"{slot_label} -> {row.get('color_code')}")

    finish_v = (row.get("finish") or "").lower()
    if finish_v and finish_v not in wood_finishes and finish_v not in metal_finishes:
        out["bad_finish"].append(f"{slot_label} -> {row.get('finish')}")

    lead = row.get("lead_time_weeks") or {}
    wood_env = wood_envelopes.get(mat_key) or wood_envelopes.get(row.get("material"))
    if wood_env and isinstance(wood_env.get("lead_time_weeks"), tuple):
        band = wood_env["lead_time_weeks"]
        if lead.get("low") is not None and not _within(lead["low"], band):
            out["out_of_lead_band"].append({"row": slot_label, "low": lead["low"], "band": band})
        if lead.get("high") is not None and not _within(lead["high"], band):
            out["out_of_lead_band"].append({"row": slot_label, "high": lead["high"], "band": band})

    cost = row.get("cost_inr_per_unit") or {}
    if wood_env and isinstance(wood_env.get("cost_inr_kg"), tuple):
        lo, hi = wood_env["cost_inr_kg"]
        scaled = (lo * price_index, hi * price_index)
        if cost.get("low") is not None and not _within(cost["low"], scaled):
            out["out_of_cost_band"].append({"row": slot_label, "low": cost["low"], "band_scaled": scaled})
        if cost.get("high") is not None and not _within(cost["high"], scaled):
            out["out_of_cost_band"].append({"row": slot_label, "high": cost["high"], "band_scaled": scaled})

    metal_env = metal_envelopes.get(mat_key) or metal_envelopes.get(row.get("material"))
    if metal_env and isinstance(metal_env.get("cost_inr_kg"), tuple):
        lo, hi = metal_env["cost_inr_kg"]
        scaled = (lo * price_index, hi * price_index)
        if cost.get("low") is not None and not _within(cost["low"], scaled):
            out["out_of_cost_band"].append({"row": slot_label, "low": cost["low"], "band_scaled": scaled})
        if cost.get("high") is not None and not _within(cost["high"], scaled):
            out["out_of_cost_band"].append({"row": slot_label, "high": cost["high"], "band_scaled": scaled})

    status = (row.get("regional_status") or "").lower()
    if status not in {"locally_available", "requires_transport", "unknown"}:
        out["bad_region"].append(slot_label)
    elif locally and status != "locally_available" and mat_key in locally:
        out["bad_region"].append(f"{slot_label}:should_be_local")
    elif remote and status != "requires_transport" and mat_key in remote:
        out["bad_region"].append(f"{slot_label}:should_be_remote")


def _validate_hardware_row(
    row: dict[str, Any],
    *,
    metal_finishes: set[str],
    metal_envelopes: dict[str, Any],
    locally: set[str],
    remote: set[str],
    price_index: float,
    out: dict[str, list[Any]],
) -> None:
    """Grade a single hardware row against the BRD hardware sub-schema."""
    label = f"hardware:{row.get('key') or row.get('item')}"
    spec = row.get("specification") or {}

    # Hardware type must be in scope.
    htype = (row.get("hardware_type") or "").lower()
    if htype not in HARDWARE_TYPES_IN_SCOPE:
        out["bad_hardware_type"].append(f"{label} -> {htype}")

    # Finish must come from the metal palette.
    fin = (spec.get("finish") or "").lower()
    if fin and fin not in metal_finishes:
        out["bad_finish"].append(f"{label} -> {row.get('specification', {}).get('finish')}")

    # Quantity must be > 0.
    qty = row.get("quantity")
    if qty is None or int(qty) <= 0:
        out["bad_quantity"].append(label)

    # Cost coherence — total ≈ per_unit × quantity (allow 1% wiggle).
    per_unit = row.get("cost_inr_per_unit") or {}
    total = row.get("cost_inr_total") or {}
    if per_unit.get("low") is not None and total.get("low") is not None and qty:
        expected_low = float(per_unit["low"]) * int(qty)
        actual_low = float(total["low"])
        if expected_low > 0 and abs(actual_low - expected_low) / expected_low > 0.01:
            out["bad_total"].append({
                "row": label, "side": "low",
                "expected": round(expected_low, 2), "actual": round(actual_low, 2),
            })
    if per_unit.get("high") is not None and total.get("high") is not None and qty:
        expected_high = float(per_unit["high"]) * int(qty)
        actual_high = float(total["high"])
        if expected_high > 0 and abs(actual_high - expected_high) / expected_high > 0.01:
            out["bad_total"].append({
                "row": label, "side": "high",
                "expected": round(expected_high, 2), "actual": round(actual_high, 2),
            })

    # Regional status sanity.
    mat_key = (spec.get("material") or "").lower().replace(" ", "_").replace("-", "_")
    status = (row.get("regional_status") or "").lower()
    if status not in {"locally_available", "requires_transport", "unknown"}:
        out["bad_region"].append(label)
    elif locally and status != "locally_available" and mat_key in locally:
        out["bad_region"].append(f"{label}:should_be_local")
    elif remote and status != "requires_transport" and mat_key in remote:
        out["bad_region"].append(f"{label}:should_be_remote")


def _validate_upholstery_row(
    row: dict[str, Any],
    *,
    upholstery_catalogue: dict[str, Any],
    foam_catalogue: dict[str, Any],
    leather_brd: dict[str, Any],
    durability_brd: dict[str, Any],
    colourfastness_min: int,
    palette_hex: set[str],
    locally: set[str],
    remote: set[str],
    price_index: float,
    out: dict[str, list[Any]],
) -> None:
    """Grade a single upholstery row against BRD bands."""
    label = f"upholstery:{row.get('key') or row.get('slot')}"
    cover = row.get("cover") or {}
    foam = row.get("foam") or {}
    backing = row.get("backing") or {}

    # Cover category + subtype.
    cat = (cover.get("category") or "").lower()
    if cat not in COVER_CATEGORIES_IN_SCOPE:
        out["bad_cover_category"].append(f"{label} -> {cat}")

    subtype_raw = (cover.get("subtype") or "").strip()
    subtype = subtype_raw.lower()
    # Catalogue keys carry uppercase grade letters (leather_genuine_grade_A) — try
    # both raw and case-folded lookup against a normalised key index.
    catalogue_index = {k.lower(): k for k in upholstery_catalogue}
    canonical_subtype_key = catalogue_index.get(subtype)
    sub_spec = upholstery_catalogue.get(canonical_subtype_key) if canonical_subtype_key else None
    if not sub_spec:
        out["bad_cover_subtype"].append(f"{label} -> {subtype}")

    # Leather grade vocabulary.
    if cat == "leather":
        grade = (cover.get("grade") or "").upper()
        if grade not in LEATHER_GRADES_IN_SCOPE:
            out["bad_leather_grade"].append(f"{label} -> {grade}")
        # Leather thickness in BRD 1.2-1.5.
        thick_band = leather_brd.get("thickness_mm") if isinstance(leather_brd, dict) else None
        if thick_band and cover.get("thickness_mm") is not None:
            if not _within(float(cover["thickness_mm"]), thick_band):
                out["out_of_thickness_band"].append({
                    "row": label,
                    "value_mm": cover["thickness_mm"],
                    "band_mm": thick_band,
                })

    # Durability rubs band.
    rubs_band = durability_brd.get("rubs_range_k") if isinstance(durability_brd, dict) else None
    rubs = cover.get("durability_rubs_k")
    if rubs_band and rubs is not None and not _within(float(rubs), rubs_band):
        out["out_of_durability_band"].append({
            "row": label, "value_k": rubs, "band_k": rubs_band,
        })

    # Colour fastness floor.
    cf = cover.get("colour_fastness_of_5")
    if cf is not None and float(cf) < float(colourfastness_min):
        out["below_colourfastness_min"].append({
            "row": label, "value": cf, "min": colourfastness_min,
        })

    # Hex from palette.
    hex_v = (cover.get("color_code") or "").lower()
    if palette_hex and hex_v and hex_v not in palette_hex:
        out["bad_hex"].append(f"{label} -> {cover.get('color_code')}")

    # Backing type vocabulary.
    btype = (backing.get("type") or "").lower()
    if btype and btype not in BACKING_TYPES_IN_SCOPE:
        out["bad_backing_type"].append(f"{label} -> {btype}")

    # Foam grade in catalogue.
    foam_grade = foam.get("grade")
    if foam_grade and foam_grade not in foam_catalogue:
        out["bad_foam_grade"].append(f"{label} -> {foam_grade}")

    # Filling weight coherence: density × area × thickness/1000 (within 5%).
    density = foam.get("density_kg_m3")
    thick = foam.get("thickness_mm")
    area = row.get("area_m2_per_piece")
    weight = foam.get("filling_weight_kg_per_piece")
    if density and thick and area and weight:
        expected = float(density) * float(area) * float(thick) / 1000.0
        if expected > 0 and abs(float(weight) - expected) / expected > 0.05:
            out["bad_filling_weight"].append({
                "row": label, "expected_kg": round(expected, 3),
                "actual_kg": round(float(weight), 3),
            })

    # Cost per m² inside BRD subtype band × city index.
    cost = row.get("cost_inr_per_m2") or {}
    if sub_spec and isinstance(sub_spec.get("cost_inr_m2"), tuple):
        lo, hi = sub_spec["cost_inr_m2"]
        scaled = (lo * price_index, hi * price_index)
        if cost.get("low") is not None and not _within(cost["low"], scaled):
            out["out_of_cost_band"].append({"row": label, "low": cost["low"], "band_scaled": scaled})
        if cost.get("high") is not None and not _within(cost["high"], scaled):
            out["out_of_cost_band"].append({"row": label, "high": cost["high"], "band_scaled": scaled})

    # Total = per_m² × area (1% wiggle).
    total = row.get("cost_inr_total") or {}
    if cost.get("low") is not None and total.get("low") is not None and area:
        expected_lo = float(cost["low"]) * float(area)
        if expected_lo > 0 and abs(float(total["low"]) - expected_lo) / expected_lo > 0.01:
            out["bad_uphol_total"].append({
                "row": label, "side": "low",
                "expected": round(expected_lo, 2), "actual": round(float(total["low"]), 2),
            })
    if cost.get("high") is not None and total.get("high") is not None and area:
        expected_hi = float(cost["high"]) * float(area)
        if expected_hi > 0 and abs(float(total["high"]) - expected_hi) / expected_hi > 0.01:
            out["bad_uphol_total"].append({
                "row": label, "side": "high",
                "expected": round(expected_hi, 2), "actual": round(float(total["high"]), 2),
            })

    # Regional status sanity (use the cover subtype family as the lookup key).
    status = (row.get("regional_status") or "").lower()
    sub_key = subtype.replace("-", "_")
    if status not in {"locally_available", "requires_transport", "unknown"}:
        out["bad_region"].append(label)
    elif locally and status != "locally_available" and sub_key in locally:
        out["bad_region"].append(f"{label}:should_be_local")
    elif remote and status != "requires_transport" and sub_key in remote:
        out["bad_region"].append(f"{label}:should_be_remote")


def _validate_finishing_row(
    row: dict[str, Any],
    *,
    finishes_catalogue: dict[str, Any],
    palette_hex: set[str],
    price_index: float,
    out: dict[str, list[Any]],
) -> None:
    label = f"finishing:{row.get('key') or row.get('applies_to')}"
    prep = row.get("preparation") or {}
    base = row.get("base_coat") or {}
    top = row.get("top_coat") or {}
    cf = row.get("colour_fastness") or {}

    primer = (prep.get("primer_type") or "").strip()
    if primer and primer not in PRIMER_TYPES_IN_SCOPE:
        out["bad_primer"].append(f"{label} -> {primer}")

    grits = prep.get("sanding_grits") or []
    if grits and any(grits[i] > grits[i + 1] for i in range(len(grits) - 1)):
        out["bad_sanding"].append(f"{label} -> sanding grits not ascending: {grits}")

    base_hex = (base.get("color_code") or "").lower()
    if palette_hex and base_hex and base_hex not in palette_hex:
        out["bad_hex"].append(f"{label} -> base_coat {base.get('color_code')}")

    system = top.get("system")
    sub_spec = finishes_catalogue.get(system)
    if not sub_spec:
        out["bad_topcoat_system"].append(f"{label} -> {system}")
    else:
        thickness = top.get("thickness_microns")
        thick_band = sub_spec.get("thickness_microns")
        if isinstance(thick_band, tuple) and thickness is not None and not _within(float(thickness), thick_band):
            out["out_of_thickness_band"].append({
                "row": label, "value_microns": thickness, "band_microns": thick_band,
            })
        coats = top.get("coats")
        coats_band = sub_spec.get("coats")
        if isinstance(coats_band, tuple) and coats is not None and not _within(float(coats), coats_band):
            out["out_of_coats_band"].append({
                "row": label, "value": coats, "band": coats_band,
            })
        cost = row.get("cost_inr_per_m2") or {}
        cost_band = sub_spec.get("cost_inr_m2")
        if isinstance(cost_band, tuple):
            lo, hi = cost_band
            scaled = (lo * price_index, hi * price_index)
            if cost.get("low") is not None and not _within(cost["low"], scaled):
                out["out_of_cost_band"].append({"row": label, "low": cost["low"], "band_scaled": scaled})
            if cost.get("high") is not None and not _within(cost["high"], scaled):
                out["out_of_cost_band"].append({"row": label, "high": cost["high"], "band_scaled": scaled})

    sheen = (top.get("sheen") or "").lower()
    if sheen and sheen not in TOPCOAT_SHEEN_IN_SCOPE:
        out["bad_sheen"].append(f"{label} -> {sheen}")

    uv = cf.get("uv_rating_of_8")
    if uv is not None and float(uv) < 6:
        out["below_uv_min"].append({"row": label, "value": uv, "min": 6})

    # Cost total = per_m² × area (1% wiggle).
    area = row.get("area_m2")
    cost = row.get("cost_inr_per_m2") or {}
    total = row.get("cost_inr_total") or {}
    if cost.get("low") is not None and total.get("low") is not None and area:
        expected_lo = float(cost["low"]) * float(area)
        if expected_lo > 0 and abs(float(total["low"]) - expected_lo) / expected_lo > 0.01:
            out["bad_finishing_total"].append({
                "row": label, "side": "low",
                "expected": round(expected_lo, 2), "actual": round(float(total["low"]), 2),
            })
    if cost.get("high") is not None and total.get("high") is not None and area:
        expected_hi = float(cost["high"]) * float(area)
        if expected_hi > 0 and abs(float(total["high"]) - expected_hi) / expected_hi > 0.01:
            out["bad_finishing_total"].append({
                "row": label, "side": "high",
                "expected": round(expected_hi, 2), "actual": round(float(total["high"]), 2),
            })


def _validate_cost_summary(
    spec: dict[str, Any],
    *,
    waste_factor_band: list[float],
    out: dict[str, list[Any]],
) -> None:
    summary = spec.get("cost_summary") or {}
    by_section = summary.get("by_section_inr") or {}
    total = summary.get("total_material_cost_inr") or {}
    waste_pct = summary.get("waste_factor_pct")
    adjusted = summary.get("adjusted_material_cost_inr") or {}

    # Waste factor in BRD band.
    if waste_pct is None or not (float(waste_factor_band[0]) - 1e-6 <= float(waste_pct) <= float(waste_factor_band[1]) + 1e-6):
        out["bad_waste_factor"].append({"value": waste_pct, "band": waste_factor_band})

    # by_section sums for hardware / upholstery / finishing match the row totals.
    def _sum_section(rows: list[dict[str, Any]], cost_key: str) -> tuple[float, float]:
        lo = sum(float((r.get(cost_key) or {}).get("low") or 0) for r in rows or [])
        hi = sum(float((r.get(cost_key) or {}).get("high") or 0) for r in rows or [])
        return lo, hi

    expected = {
        "hardware": _sum_section(spec.get("hardware") or [], "cost_inr_total"),
        "upholstery": _sum_section(spec.get("upholstery") or [], "cost_inr_total"),
        "finishing": _sum_section(spec.get("finishing") or [], "cost_inr_total"),
    }
    for section, (lo_e, hi_e) in expected.items():
        b = by_section.get(section) or {}
        for side, expected_v in (("low", lo_e), ("high", hi_e)):
            actual_v = float(b.get(side) or 0)
            if expected_v > 0 and abs(actual_v - expected_v) / max(expected_v, 1e-6) > 0.02:
                out["bad_section_sum"].append({
                    "section": section, "side": side,
                    "expected": round(expected_v, 2), "actual": round(actual_v, 2),
                })

    # Total = sum of all by_section entries.
    expected_total_lo = sum(float((by_section.get(s) or {}).get("low") or 0) for s in by_section)
    expected_total_hi = sum(float((by_section.get(s) or {}).get("high") or 0) for s in by_section)
    for side, expected_v in (("low", expected_total_lo), ("high", expected_total_hi)):
        actual_v = float(total.get(side) or 0)
        if expected_v > 0 and abs(actual_v - expected_v) / max(expected_v, 1e-6) > 0.02:
            out["bad_total_sum"].append({
                "side": side,
                "expected": round(expected_v, 2),
                "actual": round(actual_v, 2),
            })

    # Adjusted = total × (1 + waste/100) — 0.5% wiggle.
    if waste_pct is not None and total.get("low") is not None and total.get("high") is not None:
        mult = 1.0 + float(waste_pct) / 100.0
        for side in ("low", "high"):
            expected_adj = float(total[side]) * mult
            actual_adj = float(adjusted.get(side) or 0)
            if expected_adj > 0 and abs(actual_adj - expected_adj) / max(expected_adj, 1e-6) > 0.005:
                out["bad_adjusted"].append({
                    "side": side,
                    "expected": round(expected_adj, 2),
                    "actual": round(actual_adj, 2),
                })


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    palette = knowledge.get("theme_rule_pack", {}).get("material_palette", {}) or {}
    palette_pool = {
        m.lower().replace(" ", "_").replace("-", "_")
        for bucket in ("primary", "secondary", "upholstery", "accent")
        for m in palette.get(bucket, [])
    }
    palette_hex = {c.lower() for c in knowledge.get("theme_rule_pack", {}).get("colour_palette", [])}
    wood_finishes = {f.lower() for f in knowledge.get("wood_brd", {}).get("finish_palette", [])}
    metal_finishes = {f.lower() for f in knowledge.get("metal_brd", {}).get("finish_palette", [])}
    wood_envelopes = knowledge.get("wood_envelopes", {}) or {}
    metal_envelopes = knowledge.get("metal_envelopes", {}) or {}
    availability = knowledge.get("regional_availability", {}) or {}
    locally = {m.lower() for m in availability.get("locally_available", [])}
    remote = {m.lower() for m in availability.get("requires_transport", [])}
    price_index = float(knowledge.get("city_price_index") or 1.0)

    out: dict[str, list[Any]] = {
        "bad_palette": [], "bad_hex": [], "bad_finish": [],
        "out_of_lead_band": [], "out_of_cost_band": [], "bad_region": [],
        "bad_hardware_type": [], "bad_quantity": [], "bad_total": [],
        # Upholstery-specific buckets.
        "bad_cover_category": [], "bad_cover_subtype": [], "bad_leather_grade": [],
        "out_of_thickness_band": [], "out_of_durability_band": [],
        "below_colourfastness_min": [], "bad_backing_type": [], "bad_foam_grade": [],
        "bad_filling_weight": [], "bad_uphol_total": [],
        # Finishing-specific buckets.
        "bad_primer": [], "bad_sanding": [], "bad_topcoat_system": [],
        "out_of_coats_band": [], "bad_sheen": [], "below_uv_min": [],
        "bad_finishing_total": [],
        # Cost summary.
        "bad_waste_factor": [], "bad_section_sum": [],
        "bad_total_sum": [], "bad_adjusted": [],
    }

    for row in spec.get("primary_structure") or []:
        _validate_row(row, section="primary", palette_pool=palette_pool, palette_hex=palette_hex,
                      wood_finishes=wood_finishes, metal_finishes=metal_finishes,
                      wood_envelopes=wood_envelopes, metal_envelopes=metal_envelopes,
                      locally=locally, remote=remote, price_index=price_index, out=out)
    for row in spec.get("secondary_materials") or []:
        _validate_row(row, section="secondary", palette_pool=palette_pool, palette_hex=palette_hex,
                      wood_finishes=wood_finishes, metal_finishes=metal_finishes,
                      wood_envelopes=wood_envelopes, metal_envelopes=metal_envelopes,
                      locally=locally, remote=remote, price_index=price_index, out=out)
    for row in spec.get("hardware") or []:
        _validate_hardware_row(row, metal_finishes=metal_finishes,
                               metal_envelopes=metal_envelopes,
                               locally=locally, remote=remote,
                               price_index=price_index, out=out)

    upholstery_catalogue = knowledge.get("upholstery_catalogue", {}) or {}
    foam_catalogue = knowledge.get("foam_catalogue", {}) or {}
    leather_brd = (knowledge.get("upholstery_brd") or {}).get("leather", {}) or {}
    durability_brd = (knowledge.get("upholstery_brd") or {}).get("durability", {}) or {}
    colourfastness_min = (knowledge.get("upholstery_brd") or {}).get("colourfastness_min_of_5", 4)
    for row in spec.get("upholstery") or []:
        _validate_upholstery_row(
            row,
            upholstery_catalogue=upholstery_catalogue,
            foam_catalogue=foam_catalogue,
            leather_brd=leather_brd,
            durability_brd=durability_brd,
            colourfastness_min=colourfastness_min,
            palette_hex=palette_hex,
            locally=locally, remote=remote,
            price_index=price_index, out=out,
        )

    finishes_catalogue = knowledge.get("finishes_catalogue", {}) or {}
    waste_factor_band = knowledge.get("waste_factor_pct_band") or [10.0, 15.0]
    for row in spec.get("finishing") or []:
        _validate_finishing_row(
            row,
            finishes_catalogue=finishes_catalogue,
            palette_hex=palette_hex,
            price_index=price_index,
            out=out,
        )
    if spec.get("cost_summary"):
        _validate_cost_summary(spec, waste_factor_band=waste_factor_band, out=out)

    return {
        "primary_structure_count": len(spec.get("primary_structure") or []),
        "secondary_materials_count": len(spec.get("secondary_materials") or []),
        "hardware_count": len(spec.get("hardware") or []),
        "palette_members_valid": not out["bad_palette"],
        "bad_palette_materials": out["bad_palette"],
        "colour_in_palette": not out["bad_hex"],
        "out_of_palette_hex": out["bad_hex"],
        "finish_in_palette": not out["bad_finish"],
        "bad_finish": out["bad_finish"],
        "lead_time_in_band": not out["out_of_lead_band"],
        "out_of_lead_band": out["out_of_lead_band"],
        "cost_in_scaled_band": not out["out_of_cost_band"],
        "out_of_cost_band": out["out_of_cost_band"],
        "regional_status_consistent": not out["bad_region"],
        "bad_regional_status": out["bad_region"],
        "hardware_types_valid": not out["bad_hardware_type"],
        "bad_hardware_types": out["bad_hardware_type"],
        "hardware_quantities_valid": not out["bad_quantity"],
        "bad_hardware_quantities": out["bad_quantity"],
        "hardware_totals_consistent": not out["bad_total"],
        "bad_hardware_totals": out["bad_total"],
        # Upholstery section.
        "upholstery_count": len(spec.get("upholstery") or []),
        "cover_categories_valid": not out["bad_cover_category"],
        "bad_cover_categories": out["bad_cover_category"],
        "cover_subtypes_in_catalogue": not out["bad_cover_subtype"],
        "bad_cover_subtypes": out["bad_cover_subtype"],
        "leather_grades_valid": not out["bad_leather_grade"],
        "bad_leather_grades": out["bad_leather_grade"],
        "leather_thickness_in_band": not out["out_of_thickness_band"],
        "out_of_thickness_band": out["out_of_thickness_band"],
        "durability_in_band": not out["out_of_durability_band"],
        "out_of_durability_band": out["out_of_durability_band"],
        "colour_fastness_meets_min": not out["below_colourfastness_min"],
        "below_colourfastness_min": out["below_colourfastness_min"],
        "backing_types_valid": not out["bad_backing_type"],
        "bad_backing_types": out["bad_backing_type"],
        "foam_grades_in_catalogue": not out["bad_foam_grade"],
        "bad_foam_grades": out["bad_foam_grade"],
        "filling_weight_consistent": not out["bad_filling_weight"],
        "bad_filling_weights": out["bad_filling_weight"],
        "upholstery_totals_consistent": not out["bad_uphol_total"],
        "bad_upholstery_totals": out["bad_uphol_total"],
        # Finishing section.
        "finishing_count": len(spec.get("finishing") or []),
        "primer_types_valid": not out["bad_primer"],
        "bad_primers": out["bad_primer"],
        "sanding_grits_ascending": not out["bad_sanding"],
        "bad_sanding": out["bad_sanding"],
        "topcoat_systems_in_catalogue": not out["bad_topcoat_system"],
        "bad_topcoat_systems": out["bad_topcoat_system"],
        "topcoat_coats_in_band": not out["out_of_coats_band"],
        "out_of_coats_band": out["out_of_coats_band"],
        "topcoat_sheen_valid": not out["bad_sheen"],
        "bad_sheen": out["bad_sheen"],
        "uv_rating_meets_min": not out["below_uv_min"],
        "below_uv_min": out["below_uv_min"],
        "finishing_totals_consistent": not out["bad_finishing_total"],
        "bad_finishing_totals": out["bad_finishing_total"],
        # Cost summary.
        "waste_factor_in_band": not out["bad_waste_factor"],
        "bad_waste_factor": out["bad_waste_factor"],
        "section_sums_consistent": not out["bad_section_sum"],
        "bad_section_sums": out["bad_section_sum"],
        "total_sum_consistent": not out["bad_total_sum"],
        "bad_total_sum": out["bad_total_sum"],
        "adjusted_total_consistent": not out["bad_adjusted"],
        "bad_adjusted_total": out["bad_adjusted"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class MaterialSpecError(RuntimeError):
    """Raised when the LLM material-spec stage cannot produce a grounded sheet."""


async def generate_material_spec_sheet(req: MaterialSpecRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise MaterialSpecError(
            "OpenAI API key is not configured. The material-spec stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_material_spec_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise MaterialSpecError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the sheet."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": MATERIAL_SPEC_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": MATERIAL_SPEC_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for material spec sheet")
        raise MaterialSpecError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MaterialSpecError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "material_spec_sheet",
        "name": "Material Specification Sheet",
        "model": settings.openai_model,
        "theme": req.theme,
        "city": req.city or None,
        "knowledge": knowledge,
        "material_spec_sheet": spec,
        "validation": validation,
    }
