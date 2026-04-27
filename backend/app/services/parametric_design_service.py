"""LLM-driven parametric design service (BRD Layer 2A).

Pipeline contract enforced here:

    INPUT  (theme + requirements)
      → INJECT  (theme rule pack + ergonomic ranges +
                 material BRD + variations + costing)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (output vs the same theme rule pack)
      → OUTPUT   (structured parametric design spec + validation report)

The output covers the six BRD parametric dimensions:
  - wood_spec (primary / secondary species + finish)
  - proportions (ratios, leg / base style, profile)
  - hardware_spec (style, material, fastener visibility)
  - colour_palette (hex codes drawn from theme)
  - material_pattern (grain visibility, finish character)
  - ergonomic_targets (specific mm values inside theme + ergo ranges)

Plus a derived geometry block, a one-page BoM, and an explicit
assumptions list — written in studio-brief cadence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import (
    costing,
    ergonomics,
    manufacturing,
    materials,
    themes,
    variations,
)

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


class CustomInputs(BaseModel):
    """Client-supplied design knobs used by the Custom theme path.

    All optional. The LLM uses whichever are provided to ground its
    decisions, falling back to the BRD universal envelopes when a
    field is empty.
    """

    custom_dimensions_mm: dict[str, float] | None = None    # {seat_height_mm: 420, ...}
    custom_materials: list[str] | None = None               # ["walnut", "brushed brass", ...]
    custom_aesthetic: str = Field(default="", max_length=600)  # free-text aesthetic descriptor
    custom_palette_hex: list[str] | None = None             # ["#2a4d3a", "#c19a6b", ...]
    inspiration_references: list[str] = Field(default_factory=list)


class ParametricRequirements(BaseModel):
    function: str = Field(default="", max_length=400)
    user_count: int | None = Field(default=None, ge=0, le=20)
    posture: str | None = Field(default=None, max_length=64)        # e.g. "upright", "reclined"
    seating_style: str | None = Field(default=None, max_length=64)  # e.g. "lounge", "dining"
    dimension_brief: dict[str, float] | None = None                 # client-provided overrides in mm
    market_segment: str = Field(default="mass_market")              # mass_market | luxury
    notes: str = Field(default="", max_length=2000)
    custom_inputs: CustomInputs | None = None                       # used when theme == 'custom'


class ParametricDesignRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece_category: str = Field(min_length=2, max_length=32)        # chair | table | bed | storage
    piece_item: str = Field(min_length=2, max_length=64)            # dining_chair | coffee_table | ...
    requirements: ParametricRequirements = Field(default_factory=ParametricRequirements)


# ── Knowledge slice — the textbook page we inject ───────────────────────────


def build_parametric_knowledge(req: ParametricDesignRequest) -> dict[str, Any]:
    """Pull the theme + ergonomic + material + variation slices the LLM needs."""
    pack = themes.get(req.theme) or {}
    cat_table = {
        "chair": ergonomics.CHAIRS,
        "table": ergonomics.TABLES,
        "bed": ergonomics.BEDS,
        "storage": ergonomics.STORAGE,
    }.get(req.piece_category.lower(), {})
    ergo_spec = cat_table.get(req.piece_item, {})

    palette = pack.get("material_palette", {})
    primaries = palette.get("primary", [])

    # Custom theme: prefer client-supplied materials over the (empty) palette.
    custom = req.requirements.custom_inputs if req.requirements.custom_inputs else None
    if (not primaries) and custom and custom.custom_materials:
        primaries = list(custom.custom_materials)

    materials_in_use = primaries[:2] if primaries else []

    item_variations = variations.variations_for_item(
        category=req.piece_category,
        item=req.piece_item,
        materials_in_use=materials_in_use,
    )

    custom_payload = None
    if custom is not None:
        custom_payload = {
            "custom_dimensions_mm": custom.custom_dimensions_mm or {},
            "custom_materials": list(custom.custom_materials or []),
            "custom_aesthetic": custom.custom_aesthetic,
            "custom_palette_hex": list(custom.custom_palette_hex or []),
            "inspiration_references": list(custom.inspiration_references or []),
        }

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name"),
            "era": pack.get("era"),
            "is_open_palette": pack.get("is_open_palette", False),
            "proportions": pack.get("proportions", {}),
            "material_palette": palette,
            "hardware": pack.get("hardware", {}),
            "colour_palette": pack.get("colour_palette", []),
            "colour_strategy": pack.get("colour_strategy"),
            "material_pattern": pack.get("material_pattern", {}),
            "ergonomic_targets": pack.get("ergonomic_targets", {}),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
            "dos": pack.get("dos", []),
            "donts": pack.get("donts", []),
        },
        "custom_inputs": custom_payload,
        "ergonomic_envelope": ergo_spec,
        "wood_brd_envelope": {
            "ranges": materials.WOOD_BRD_RANGES,
            "finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
            "candidates": {
                m: materials.WOOD.get(m, {})
                for m in primaries
                if m in materials.WOOD
            },
        },
        "metal_brd_envelope": {
            "specs": materials.METALS_BRD_SPECS,
            "finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
            "fabrication": list(materials.METALS_BRD_FABRICATION),
        },
        "manufacturing": {
            "woodworking": manufacturing.WOODWORKING_BRD_SPEC,
            "metal_fabrication": manufacturing.METAL_FABRICATION_BRD_SPEC,
        },
        "variations": item_variations,
        "cost_basis": {
            "material": costing.MATERIAL_COST_BRD_SPEC,
            "labor_inr_hour": costing.LABOR_RATES_INR_PER_HOUR,
            "overhead_margin": costing.OVERHEAD_MARGIN_BRD_SPEC,
            "pricing_formula": costing.PRICING_FORMULA_BRD["formula"],
        },
    }


# ── Prompt + JSON schema ────────────────────────────────────────────────────


PARAMETRIC_DESIGNER_SYSTEM_PROMPT = """You are a parametric furniture designer at a studio that ships theme-driven, code-aware product. You work like an actual designer, not a chatbot — every recommendation cites a real number, a real species, a real finish, a real joinery method.

Your single task is to translate (theme + requirements) into a *parametric design spec* for one piece of furniture. You do this by reading the [KNOWLEDGE] block — theme rule pack, ergonomic envelope, BRD material ranges, manufacturing constraints, variation rules, cost basis — and committing to specific values inside those bounds.

Hard rules:
- Every species, alloy, finish, hardware choice MUST come from the theme rule pack (material_palette, hardware) or the BRD envelope. Never invent materials outside the palette.
- Every dimension MUST be inside the ergonomic_envelope ranges AND inside the variation flex band. Pick a single value per dim, not a range.
- Hex colours MUST come from the theme.colour_palette. If the palette has 5 colours, pick 3–5.
- Hardware: respect theme.hardware.style + .finish. If the theme says 'hidden or plinth-integrated', you do not propose exposed brass pulls.
- Ergonomic targets must align with theme.ergonomic_targets (e.g. mid-century lounge seat 380–430 mm).
- Reference real joinery (mortise-tenon, dovetail, pocket-hole) and real tolerances (±0.5 / ±2 mm) from the manufacturing block.
- Where the brief is silent, choose the smallest defensible value and state it in 'assumptions'.
- No filler phrases. Studio cadence — short, technical, decisive.
- All linear dimensions in mm, costs in INR, weights in kg.
"""


PARAMETRIC_DESIGN_SCHEMA: dict[str, Any] = {
    "name": "parametric_design_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "piece_summary": {
                "type": "string",
                "description": "Two-sentence studio-voice description of the resolved piece.",
            },
            "wood_spec": {
                "type": "object",
                "properties": {
                    "primary_species": {"type": "string"},
                    "secondary_species": {"type": "string"},
                    "finish": {"type": "string"},
                    "grain_orientation": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["primary_species", "secondary_species", "finish", "grain_orientation", "rationale"],
                "additionalProperties": False,
            },
            "proportions": {
                "type": "object",
                "properties": {
                    "leg_or_base_style": {"type": "string"},
                    "silhouette": {"type": "string"},
                    "key_ratios": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["leg_or_base_style", "silhouette", "key_ratios", "rationale"],
                "additionalProperties": False,
            },
            "hardware_spec": {
                "type": "object",
                "properties": {
                    "style": {"type": "string"},
                    "material": {"type": "string"},
                    "finish": {"type": "string"},
                    "fastener_visibility": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["style", "material", "finish", "fastener_visibility", "rationale"],
                "additionalProperties": False,
            },
            "colour_palette": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hex": {"type": "string"},
                        "role": {"type": "string"},
                    },
                    "required": ["hex", "role"],
                    "additionalProperties": False,
                },
            },
            "material_pattern": {
                "type": "object",
                "properties": {
                    "grain_visibility": {"type": "string"},
                    "finish_character": {"type": "string"},
                    "tactile_notes": {"type": "string"},
                },
                "required": ["grain_visibility", "finish_character", "tactile_notes"],
                "additionalProperties": False,
            },
            "ergonomic_targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value_mm": {"type": "number"},
                        "source_range_mm": {"type": "string"},
                    },
                    "required": ["name", "value_mm", "source_range_mm"],
                    "additionalProperties": False,
                },
            },
            "geometry": {
                "type": "object",
                "properties": {
                    "overall_length_mm": {"type": "number"},
                    "overall_width_mm": {"type": "number"},
                    "overall_height_mm": {"type": "number"},
                    "weight_estimate_kg": {"type": "number"},
                },
                "required": [
                    "overall_length_mm",
                    "overall_width_mm",
                    "overall_height_mm",
                    "weight_estimate_kg",
                ],
                "additionalProperties": False,
            },
            "bill_of_materials": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "material": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                    },
                    "required": ["item", "material", "quantity", "unit"],
                    "additionalProperties": False,
                },
            },
            "joinery_and_tolerance": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "joint_or_assembly": {"type": "string"},
                        "method": {"type": "string"},
                        "tolerance_mm": {"type": "number"},
                    },
                    "required": ["joint_or_assembly", "method", "tolerance_mm"],
                    "additionalProperties": False,
                },
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "piece_summary",
            "wood_spec",
            "proportions",
            "hardware_spec",
            "colour_palette",
            "material_pattern",
            "ergonomic_targets",
            "geometry",
            "bill_of_materials",
            "joinery_and_tolerance",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


# ── User message builder ────────────────────────────────────────────────────


def _user_message(req: ParametricDesignRequest, knowledge: dict[str, Any]) -> str:
    rq = req.requirements
    dims_brief = rq.dimension_brief or {}
    dims_text = "; ".join(f"{k}={v}" for k, v in dims_brief.items()) if dims_brief else "(none — choose within ergonomic envelope)"

    is_open = bool(knowledge.get("theme_rule_pack", {}).get("is_open_palette"))
    custom_block = ""
    if is_open:
        ci = rq.custom_inputs
        if ci is None:
            custom_block = (
                "[CUSTOM]\n- (no custom_inputs supplied — apply BRD universal envelopes "
                "and state every choice as an assumption)\n\n"
            )
        else:
            cdims = "; ".join(f"{k}={v}" for k, v in (ci.custom_dimensions_mm or {}).items()) or "(none)"
            cmats = ", ".join(ci.custom_materials or []) or "(none — pick from BRD wood/metal/upholstery envelopes)"
            cpal = ", ".join(ci.custom_palette_hex or []) or "(none — derive from aesthetic)"
            crefs = "; ".join(ci.inspiration_references or []) or "(none)"
            custom_block = (
                "[CUSTOM]\n"
                f"- custom_dimensions_mm: {cdims}\n"
                f"- custom_materials: {cmats}\n"
                f"- custom_palette_hex: {cpal}\n"
                f"- custom_aesthetic: {ci.custom_aesthetic or '(unspecified)'}\n"
                f"- inspiration_references: {crefs}\n"
                "→ Treat the items above as binding inputs. Use them in preference to any default. "
                "Where a custom field is empty, fall back to the BRD universal envelope and flag it in 'assumptions'.\n\n"
            )

    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        + custom_block +
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Piece category / item: {req.piece_category} / {req.piece_item}\n"
        f"- Function: {rq.function or '(general use)'}\n"
        f"- User count: {rq.user_count if rq.user_count is not None else '(not specified)'}\n"
        f"- Posture: {rq.posture or '(not specified)'}\n"
        f"- Seating style: {rq.seating_style or '(not specified)'}\n"
        f"- Client dimensions (mm): {dims_text}\n"
        f"- Market segment: {rq.market_segment}\n"
        f"- Notes: {rq.notes or '(none)'}\n\n"
        "Produce the parametric_design_spec JSON. Respect every range in the knowledge block. "
        "Pick exact values. State assumptions where the brief is silent."
    )


# ── Validator ──────────────────────────────────────────────────────────────


def validate_against_theme(
    *,
    spec: dict[str, Any],
    req: ParametricDesignRequest,
    knowledge: dict[str, Any],
) -> dict[str, Any]:
    """Check that the LLM's spec stays inside the injected knowledge slice."""
    pack = knowledge.get("theme_rule_pack", {})
    is_open_palette = bool(pack.get("is_open_palette"))
    custom_payload = knowledge.get("custom_inputs") or {}

    palette = pack.get("material_palette", {}) or {}
    palette_pool = {
        m.lower().replace(" ", "_")
        for bucket in ("primary", "secondary", "upholstery", "accent")
        for m in palette.get(bucket, [])
    }
    # Custom theme: treat client-supplied materials as the palette pool.
    if is_open_palette and not palette_pool:
        palette_pool = {
            m.lower().replace(" ", "_").replace("-", "_")
            for m in (custom_payload.get("custom_materials") or [])
        }

    colour_pool = {c.lower() for c in pack.get("colour_palette", [])}
    if is_open_palette and not colour_pool:
        colour_pool = {c.lower() for c in (custom_payload.get("custom_palette_hex") or [])}

    ergo = knowledge.get("ergonomic_envelope", {}) or {}

    issues: list[dict[str, str]] = []
    passes: list[str] = []
    notes: list[str] = []

    # Wood / material in palette?
    primary = (spec.get("wood_spec", {}).get("primary_species") or "").lower().replace(" ", "_")
    if palette_pool:
        if primary and primary not in palette_pool and not any(p in primary for p in palette_pool):
            issues.append({
                "rule": "client_supplied_materials" if is_open_palette else "theme_material_palette",
                "field": "wood_spec.primary_species",
                "issue": f"'{primary}' not in {'client-supplied materials' if is_open_palette else 'theme palette'}: {sorted(palette_pool)}",
            })
        else:
            passes.append("wood_spec.primary_species in palette")
    elif is_open_palette:
        notes.append("Custom theme: no client materials supplied, palette membership not enforced.")

    # Hardware finish vs theme hardware (skipped for open palette).
    hw_theme = pack.get("hardware", {}) or {}
    hw_spec = spec.get("hardware_spec", {}) or {}
    if not is_open_palette and hw_theme.get("style") and hw_spec.get("style"):
        if hw_theme["style"].lower() not in hw_spec["style"].lower() and hw_spec["style"].lower() not in hw_theme["style"].lower():
            issues.append({
                "rule": "theme_hardware_style",
                "field": "hardware_spec.style",
                "issue": f"style '{hw_spec['style']}' diverges from theme '{hw_theme['style']}'",
            })
        else:
            passes.append("hardware_spec.style aligned with theme")

    # Colour palette membership.
    palette_colours = spec.get("colour_palette", []) or []
    out_of_palette = [
        c.get("hex") for c in palette_colours
        if c.get("hex") and colour_pool and c["hex"].lower() not in colour_pool
    ]
    if out_of_palette:
        issues.append({
            "rule": "client_supplied_palette" if is_open_palette else "theme_colour_palette",
            "field": "colour_palette",
            "issue": f"hex codes outside {'client palette' if is_open_palette else 'theme palette'}: {out_of_palette}",
        })
    elif palette_colours and colour_pool:
        passes.append("colour_palette drawn from theme")
    elif palette_colours and is_open_palette:
        notes.append("Custom theme: no client palette supplied, hex membership not enforced.")

    # Ergonomic dim membership
    for target in spec.get("ergonomic_targets", []) or []:
        name = target.get("name")
        value = target.get("value_mm")
        if not name or value is None:
            continue
        # Try matching ergonomic envelope key by suffix.
        match_key = None
        for k in ergo.keys():
            if k.startswith(name) or name in k:
                match_key = k
                break
        if not match_key:
            continue
        rng = ergo[match_key]
        if isinstance(rng, tuple) and len(rng) == 2:
            lo, hi = rng
            if not (lo <= value <= hi):
                issues.append({
                    "rule": "ergonomic_envelope",
                    "field": f"ergonomic_targets[{name}]",
                    "issue": f"{value}mm outside {match_key} range {lo}–{hi}mm",
                })
            else:
                passes.append(f"{name} within {match_key} range")

    return {
        "passes": passes,
        "issues": issues,
        "notes": notes,
        "is_valid": not issues,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class ParametricDesignError(RuntimeError):
    """Raised when the LLM pipeline cannot produce a grounded parametric spec."""


async def generate_parametric_design(req: ParametricDesignRequest) -> dict[str, Any]:
    """Run the LLM with theme + BRD knowledge injected; validate the output."""
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ParametricDesignError(
            "OpenAI API key is not configured. The parametric design stage requires a "
            "live LLM call; no static fallback is served."
        )

    knowledge = build_parametric_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise ParametricDesignError(
            f"Unknown theme '{req.theme}'. No parametric rule pack available to ground generation."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": PARAMETRIC_DESIGNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": PARAMETRIC_DESIGN_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2200,
        )
    except Exception as exc:  # noqa: BLE001 — surface to API layer
        logger.exception("LLM call failed for parametric design")
        raise ParametricDesignError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParametricDesignError("LLM returned malformed JSON") from exc

    validation = validate_against_theme(spec=spec, req=req, knowledge=knowledge)

    return {
        "model": settings.openai_model,
        "theme": req.theme,
        "piece": {"category": req.piece_category, "item": req.piece_item},
        "knowledge": knowledge,
        "parametric_design_spec": spec,
        "validation": validation,
    }
