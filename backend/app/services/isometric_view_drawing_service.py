"""LLM-driven Isometric / 3D drawing service (BRD Layer 3A #4).

Authors the *isometric_view_spec* — overall form visualisation, the
parts breakdown (with optional explode offsets), the material-finish
palette (texture + colour), the dimensions to superimpose, and a few
short assembly notes.

Pipeline contract — same as all the other LLM services:

    INPUT (theme + piece envelope + parametric_spec)
      → INJECT  (theme palette + hardware + signature moves +
                 ergonomic envelope + material BRD finishes +
                 hatch + scale catalogues)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic isometric_view base with LLM-supplied spec)
      → OUTPUT  (isometric_view_spec JSON + technical SVG)

The five BRD requirements:
  • Overall form visualisation
  • Material finishes shown (texture, colour)
  • Assembly exploded view (optional)
  • Dimensions superimposed
  • Scale: 1:10
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import ergonomics, materials, themes
from app.services.drawings import isometric_view, plan_view
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


VIEW_MODES = ("iso", "perspective")


# ── Request schema ──────────────────────────────────────────────────────────


class IsometricViewRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: ElevationPiece | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    view_mode: str = Field(default="iso", max_length=16)
    explode_enabled: bool = Field(default=False)
    sheet_title: str = Field(default="Isometric View", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=760, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _resolve_piece_envelope(req: IsometricViewRequest) -> dict[str, Any]:
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


def build_isometric_knowledge(req: IsometricViewRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    piece = _resolve_piece_envelope(req)

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "material_palette": pack.get("material_palette", {}),
            "colour_palette": pack.get("colour_palette", []),
            "hardware": pack.get("hardware", {}),
            "material_pattern": pack.get("material_pattern", {}),
            "signature_moves": pack.get("signature_moves", []),
        },
        "piece_envelope": piece,
        "ergonomic_envelope_mm": _ergonomic_lookup(piece.get("type", "")) if piece else {},
        "scale_options": list(plan_view.SCALE_OPTIONS),
        "view_modes_in_scope": list(VIEW_MODES),
        "hatch_vocabulary": list(plan_view.HATCH_PATTERNS.keys()),
        "wood_finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        "metal_finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


ISOMETRIC_AUTHOR_SYSTEM_PROMPT = """You are an architectural draftsperson preparing the *isometric / 3D* sheet of a project drawing set. You produce the full-piece visualisation: overall form, parts breakdown (with optional exploded view), material finishes (texture + colour), and the dimensions worth superimposing on the iso projection.

Read the [KNOWLEDGE] block — piece envelope, ergonomic envelope, theme palette + hardware + colour catalogue, BRD wood / metal finish palettes, hatch + scale + view-mode catalogues — and write a structured isometric_view_spec.

Hard rules:
- view_mode MUST be in view_modes_in_scope.
- scale MUST be in scale_options. Default to 1:10 per BRD; promote to 1:20 for pieces over 1.5 m and 1:50 for room-scale.
- Each parts[i].hatch_key MUST be in hatch_vocabulary.
- finishes_legend[i].finish_label MUST come from wood_finish_palette (for wood hatches) or metal_finish_palette (for metal hatches), or be a clearly described synthetic / fabric / stone finish.
- Every colour_hex MUST come from theme.colour_palette.
- parts must collectively account for the overall envelope (sum of part bboxes ≈ piece dimensions); position parts using their own x_mm / y_mm / z_mm origin in the piece's local frame (y is height, x is length, z is depth).
- explode_offset_mm only matters when explode_enabled=True; pull parts apart along the axis that best reveals the assembly (e.g. legs along y, top apart from frame along y, fabric off the foam along z).
- key_dimensions[] superimpose overall L × W × H by default; add intermediate dims only when they clarify the form.
- Studio voice — short, technical, decisive."""


ISOMETRIC_VIEW_SCHEMA: dict[str, Any] = {
    "name": "isometric_view_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sheet_narrative": {"type": "string"},
            "view_mode": {"type": "string"},
            "scale": {"type": "string"},
            "scale_rationale": {"type": "string"},
            "explode_enabled": {"type": "boolean"},
            "explode_factor": {"type": "number"},
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "hatch_key": {"type": "string"},
                        "color_hex": {"type": "string"},
                        "finish_label": {"type": "string"},
                        "x_mm": {"type": "number"},
                        "y_mm": {"type": "number"},
                        "z_mm": {"type": "number"},
                        "length_mm": {"type": "number"},
                        "height_mm": {"type": "number"},
                        "depth_mm": {"type": "number"},
                        "explode_offset_mm": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "label", "hatch_key", "color_hex", "finish_label",
                        "x_mm", "y_mm", "z_mm",
                        "length_mm", "height_mm", "depth_mm",
                        "explode_offset_mm",
                    ],
                    "additionalProperties": False,
                },
            },
            "finishes_legend": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "finish_label": {"type": "string"},
                        "hatch_key": {"type": "string"},
                        "color_hex": {"type": "string"},
                        "applied_to": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["finish_label", "hatch_key", "color_hex", "applied_to"],
                    "additionalProperties": False,
                },
            },
            "key_dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "axis": {"type": "string"},   # x / y / z
                        "value_mm": {"type": "number"},
                    },
                    "required": ["label", "axis", "value_mm"],
                    "additionalProperties": False,
                },
            },
            "assembly_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "sheet_narrative",
            "view_mode",
            "scale",
            "scale_rationale",
            "explode_enabled",
            "explode_factor",
            "parts",
            "finishes_legend",
            "key_dimensions",
            "assembly_notes",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: IsometricViewRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Requested view_mode: {req.view_mode}\n"
        f"- Explode requested: {req.explode_enabled}\n"
        f"- Sheet title: {req.sheet_title}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the isometric_view_spec JSON. Break the piece into named parts, "
        "assign each its hatch + colour from the theme palette, list finishes once "
        "in the legend, and superimpose at least overall L × W × H. "
        "When explode_enabled is True, pick offsets that reveal the assembly logic."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any], piece: dict[str, Any]) -> dict[str, Any]:
    scale_ok = spec.get("scale") in knowledge.get("scale_options", [])
    view_ok = spec.get("view_mode") in knowledge.get("view_modes_in_scope", [])
    hatch_vocab = set(knowledge.get("hatch_vocabulary", []))
    palette_hex = {c.lower() for c in knowledge.get("theme_rule_pack", {}).get("colour_palette", [])}

    bad_hatches = [p.get("hatch_key") for p in (spec.get("parts") or []) if (p.get("hatch_key") or "").lower() not in hatch_vocab]
    out_of_palette_hex = [
        p.get("color_hex") for p in (spec.get("parts") or [])
        if palette_hex and (p.get("color_hex") or "").lower() not in palette_hex
    ]

    # Coverage — sum of part bbox volumes vs piece envelope volume.
    piece_vol = 1.0
    for k in ("length", "width", "height"):
        v = (piece.get("dimensions_mm") or {}).get(k)
        if v:
            piece_vol *= float(v)
    parts_vol = 0.0
    for p in spec.get("parts") or []:
        parts_vol += float(p.get("length_mm") or 0) * float(p.get("height_mm") or 0) * float(p.get("depth_mm") or 0)
    coverage_ratio = (parts_vol / piece_vol) if piece_vol > 0 else 0.0

    # Explode factor sanity.
    explode_factor = float(spec.get("explode_factor") or 0.0)
    explode_consistent = (
        (spec.get("explode_enabled") and 0.0 < explode_factor <= 2.0)
        or (not spec.get("explode_enabled") and explode_factor == 0.0)
    )

    return {
        "scale_in_catalogue": scale_ok,
        "view_mode_in_catalogue": view_ok,
        "hatch_vocab_valid": not bad_hatches,
        "bad_hatch_keys": bad_hatches,
        "colour_in_palette": not out_of_palette_hex,
        "out_of_palette_hex": out_of_palette_hex,
        "parts_volume_coverage_ratio": round(coverage_ratio, 3),
        "explode_factor_consistent": explode_consistent,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class IsometricViewError(RuntimeError):
    """Raised when the LLM iso stage cannot produce a grounded spec."""


async def generate_isometric_view_drawing(req: IsometricViewRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise IsometricViewError(
            "OpenAI API key is not configured. The isometric stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_isometric_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise IsometricViewError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the drawing."
        )
    if not knowledge.get("piece_envelope"):
        raise IsometricViewError(
            "No piece envelope supplied; isometric view requires an explicit piece."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": ISOMETRIC_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ISOMETRIC_VIEW_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for isometric drawing")
        raise IsometricViewError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IsometricViewError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge, knowledge["piece_envelope"])

    rendered = isometric_view.render_isometric_view(
        piece=knowledge.get("piece_envelope"),
        isometric_spec=spec,
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
        sheet_title=req.sheet_title,
    )

    return {
        "id": "isometric_view",
        "name": "Isometric View",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "isometric_view_spec": spec,
        "svg": rendered["svg"],
        "validation": validation,
        "meta": {
            **rendered.get("meta", {}),
            "part_count_specced": len(spec.get("parts", [])),
            "finishes_count_specced": len(spec.get("finishes_legend", [])),
            "key_dim_count_specced": len(spec.get("key_dimensions", [])),
        },
    }
