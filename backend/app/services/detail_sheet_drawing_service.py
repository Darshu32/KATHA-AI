"""LLM-driven Detail Sheet drawing service (BRD Layer 3A #5).

Authors a sheet of zoomed-in details — joints, hardware interfaces,
edge treatments, upholstery seams, material transitions — each cell
self-contained with its own scale, sketch, and short notes.

Pipeline contract — same as the rest of the LLM services:

    INPUT (theme + piece envelope + parametric_spec)
      → INJECT  (joinery catalogue + tolerances + manufacturing QA gates +
                 hardware rules + finishes + upholstery webbing/stitch BRD)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic detail_sheet base with LLM-supplied cells)
      → OUTPUT  (detail_sheet_spec JSON + technical SVG)

The five BRD requirements:
  • Joint details (mortise-tenon, dovetail)
  • Hardware interface (mounting, assembly)
  • Edge treatment & finish
  • Seam / stitching detail (upholstery)
  • Material transitions
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import manufacturing, materials, themes
from app.services.drawings import detail_sheet
from app.services.elevation_view_drawing_service import (
    ElevationPiece,
    _ergonomic_lookup,
    _midpoint,
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


class DetailSheetRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: ElevationPiece | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    sheet_title: str = Field(default="Detail Sheet", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=820, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _resolve_piece_envelope(req: DetailSheetRequest) -> dict[str, Any]:
    if req.piece is None:
        return {}
    d = req.piece.dimensions_mm or {}
    e = req.piece.ergonomic_targets_mm or {}
    if not d:
        ergo = _ergonomic_lookup(req.piece.type)
        d = {
            "length": _midpoint(ergo.get("overall_width_mm")) or 800,
            "width": _midpoint(ergo.get("overall_depth_mm")) or 800,
            "height": _midpoint(ergo.get("overall_height_mm")) or 850,
        }
    return {
        "type": req.piece.type,
        "dimensions_mm": d,
        "ergonomic_targets_mm": e,
        "material_hatch_key": req.piece.material_hatch_key,
        "leg_base_hatch_key": req.piece.leg_base_hatch_key,
    }


def build_detail_knowledge(req: DetailSheetRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    piece = _resolve_piece_envelope(req)
    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "hardware": pack.get("hardware", {}),
            "material_palette": pack.get("material_palette", {}),
            "material_pattern": pack.get("material_pattern", {}),
            "signature_moves": pack.get("signature_moves", []),
            "dos": pack.get("dos", []),
            "donts": pack.get("donts", []),
        },
        "piece_envelope": piece,
        "joinery_catalogue": {k: dict(v) for k, v in manufacturing.JOINERY.items()},
        "tolerances_mm": {k: v["+-mm"] for k, v in manufacturing.TOLERANCES.items()},
        "qa_gates": list(manufacturing.QUALITY_GATES_BRD_SPEC),
        "upholstery_assembly_brd": dict(manufacturing.UPHOLSTERY_ASSEMBLY_BRD_SPEC),
        "wood_finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        "metal_finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
        "scale_options": list(detail_sheet.DETAIL_SCALE_OPTIONS),
        "detail_types_in_scope": list(detail_sheet.DETAIL_TYPES),
        "joint_subtypes_in_scope": list(detail_sheet.JOINT_SUBTYPES),
        "edge_profiles_in_scope": list(detail_sheet.EDGE_PROFILES),
        "seam_types_in_scope": list(detail_sheet.SEAM_TYPES),
        "hatch_vocabulary": list(detail_sheet.HATCH_PATTERNS.keys()),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


DETAIL_AUTHOR_SYSTEM_PROMPT = """You are an architectural draftsperson preparing the *detail sheet* — the page of zoomed-in construction details that production reads alongside the working drawings. You decide which 4–9 details deserve a cell, which scale each cell needs, and what to annotate.

Read the [KNOWLEDGE] block — joinery catalogue + tolerances, QA gates, upholstery assembly BRD (webbing tension, stitch density, foam tolerance), wood + metal finish palettes, theme hardware rules, scale + hatch vocabularies — and write a structured detail_sheet_spec.

Hard rules:
- Each cell.detail_type MUST be in detail_types_in_scope.
- For joint cells: subtype MUST be in joint_subtypes_in_scope; tolerance_mm MUST come from tolerances_mm.
- For edge cells: profile MUST be in edge_profiles_in_scope.
- For seam cells: seam_type MUST be in seam_types_in_scope; stitch_density_per_inch MUST come from upholstery_assembly_brd.stitch_density_per_inch (4–6).
- For hardware cells: respect theme.hardware rules; do not propose visible knobs if theme says hidden / plinth-integrated.
- For material_transition cells: from_material + to_material MUST be in hatch_vocabulary.
- Every cell.scale MUST be in scale_options.
- Cover at least 4 cells across at least 3 different detail_types — production reads multi-aspect detail sheets, not single-detail dumps.
- Studio voice — short, technical, decisive. Each cell gets at most one short note line."""


DETAIL_SHEET_SCHEMA: dict[str, Any] = {
    "name": "detail_sheet_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sheet_narrative": {"type": "string"},
            "columns": {"type": "integer"},
            "cells": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                        "detail_type": {"type": "string"},
                        "scale": {"type": "string"},
                        "subtype": {"type": "string"},
                        "members": {"type": "array", "items": {"type": "string"}},
                        "tolerance_mm": {"type": "number"},
                        "hardware_type": {"type": "string"},
                        "mounting": {"type": "string"},
                        "fastener": {"type": "string"},
                        "profile": {"type": "string"},
                        "radius_mm": {"type": "number"},
                        "seam_type": {"type": "string"},
                        "stitch_density_per_inch": {"type": "number"},
                        "from_material": {"type": "string"},
                        "to_material": {"type": "string"},
                        "transition_detail": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": [
                        "key", "title", "detail_type", "scale",
                        "subtype", "members", "tolerance_mm",
                        "hardware_type", "mounting", "fastener",
                        "profile", "radius_mm",
                        "seam_type", "stitch_density_per_inch",
                        "from_material", "to_material", "transition_detail",
                        "note",
                    ],
                    "additionalProperties": False,
                },
            },
            "qa_links": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["sheet_narrative", "columns", "cells", "qa_links", "assumptions"],
        "additionalProperties": False,
    },
}


def _user_message(req: DetailSheetRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Sheet title: {req.sheet_title}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the detail_sheet_spec JSON. Pick 4–9 cells across at least 3 detail_types "
        "covering joints + hardware + edge or seam + material transition. "
        "Cite real BRD numbers (joinery tolerance, stitch density 4–6/in, finish from palette). "
        "Where a per-type field doesn't apply to a cell, set it to a blank-ish default ('' / 0)."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    detail_types = set(knowledge.get("detail_types_in_scope", []))
    joint_subtypes = set(knowledge.get("joint_subtypes_in_scope", []))
    edge_profiles = set(knowledge.get("edge_profiles_in_scope", []))
    seam_types = set(knowledge.get("seam_types_in_scope", []))
    scales = set(knowledge.get("scale_options", []))
    hatches = set(knowledge.get("hatch_vocabulary", []))

    bad_types: list[str] = []
    bad_scales: list[str] = []
    bad_subtypes: list[str] = []
    bad_profiles: list[str] = []
    bad_seams: list[str] = []
    bad_transition_materials: list[str] = []

    cells = spec.get("cells") or []
    for c in cells:
        dt = (c.get("detail_type") or "").lower()
        if dt not in detail_types:
            bad_types.append(dt)
            continue
        if (c.get("scale") or "") not in scales:
            bad_scales.append(c.get("scale") or "")
        if dt == "joint" and (c.get("subtype") or "") not in joint_subtypes:
            bad_subtypes.append(c.get("subtype") or "")
        if dt == "edge_treatment" and (c.get("profile") or "") not in edge_profiles:
            bad_profiles.append(c.get("profile") or "")
        if dt == "seam_stitching" and (c.get("seam_type") or "") not in seam_types:
            bad_seams.append(c.get("seam_type") or "")
        if dt == "material_transition":
            if (c.get("from_material") or "").lower() not in hatches:
                bad_transition_materials.append(f"from:{c.get('from_material')}")
            if (c.get("to_material") or "").lower() not in hatches:
                bad_transition_materials.append(f"to:{c.get('to_material')}")

    detail_type_diversity = len({(c.get("detail_type") or "").lower() for c in cells if (c.get("detail_type") or "").lower() in detail_types})

    return {
        "cell_count": len(cells),
        "detail_types_valid": not bad_types,
        "bad_detail_types": bad_types,
        "scales_valid": not bad_scales,
        "bad_scales": bad_scales,
        "joint_subtypes_valid": not bad_subtypes,
        "bad_joint_subtypes": bad_subtypes,
        "edge_profiles_valid": not bad_profiles,
        "bad_edge_profiles": bad_profiles,
        "seam_types_valid": not bad_seams,
        "bad_seam_types": bad_seams,
        "transition_materials_valid": not bad_transition_materials,
        "bad_transition_materials": bad_transition_materials,
        "detail_type_diversity": detail_type_diversity,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class DetailSheetError(RuntimeError):
    """Raised when the LLM detail-sheet stage cannot produce a grounded spec."""


async def generate_detail_sheet_drawing(req: DetailSheetRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise DetailSheetError(
            "OpenAI API key is not configured. The detail-sheet stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_detail_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise DetailSheetError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the drawing."
        )
    if not knowledge.get("piece_envelope"):
        raise DetailSheetError(
            "No piece envelope supplied; detail sheets need a piece to detail."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": DETAIL_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": DETAIL_SHEET_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for detail-sheet drawing")
        raise DetailSheetError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DetailSheetError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)
    rendered = detail_sheet.render_detail_sheet(
        detail_spec=spec,
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
        sheet_title=req.sheet_title,
    )

    return {
        "id": "detail_sheet",
        "name": "Detail Sheet",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "detail_sheet_spec": spec,
        "svg": rendered["svg"],
        "validation": validation,
        "meta": {
            **rendered.get("meta", {}),
            "cell_count_specced": len(spec.get("cells", [])),
            "qa_links_count": len(spec.get("qa_links", [])),
        },
    }
