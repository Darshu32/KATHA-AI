"""LLM-driven Section View drawing service (BRD Layer 3A #3).

Authors the *section_view_spec* — the cut-through detail page covering
internal layers (frame / foam / fabric), joinery at specific positions,
reinforcement points, seat depth, back angle, and leg taper geometry.

Pipeline contract — same as the rest of the LLM services:

    INPUT (theme + piece envelope + parametric_spec)
      → INJECT  (ergonomic envelope + manufacturing joinery / tolerances +
                 material BRD envelopes (foam, leather, fabric, wood) +
                 hatch + scale + joinery + reinforcement vocabularies)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic section_view base with LLM-supplied spec)
      → OUTPUT  (section_view_spec JSON + technical SVG)

The five BRD requirements:
  • Internal structure (joints, reinforcement)
  • Seat depth, back angle
  • Leg taper details
  • Foam / upholstery layers
  • Scale: 1:5 or 1:10 (larger for detail)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import ergonomics, manufacturing, materials, themes
from app.services.drawings import section_view
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


class SectionViewRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: ElevationPiece | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    cut_label: str = Field(default="A-A", max_length=8)
    view_target: str = Field(default="through_seat", max_length=64)  # through_seat / through_arm / through_leg
    sheet_title: str = Field(default="Section View", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=760, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _resolve_piece_envelope(req: SectionViewRequest) -> dict[str, Any]:
    if req.piece is not None:
        d = req.piece.dimensions_mm or {}
        e = req.piece.ergonomic_targets_mm or {}
        if not d:
            ergo = _ergonomic_lookup(req.piece.type)
            d = {
                "length": _midpoint(ergo.get("overall_width_mm")) or 800,
                "width": _midpoint(ergo.get("overall_depth_mm")) or 800,
                "height": _midpoint(ergo.get("overall_height_mm")) or 850,
            }
        if not e:
            ergo = _ergonomic_lookup(req.piece.type)
            e = {
                "seat_height_mm": _midpoint(ergo.get("seat_height_mm")),
                "seat_depth_mm": _midpoint(ergo.get("seat_depth_mm")),
                "back_height_mm": _midpoint(ergo.get("backrest_height_mm")),
                "arm_height_mm": _midpoint(ergo.get("arm_height_mm")),
            }
            e = {k: v for k, v in e.items() if v is not None}
        return {
            "type": req.piece.type,
            "dimensions_mm": d,
            "ergonomic_targets_mm": e,
            "material_hatch_key": req.piece.material_hatch_key,
            "leg_base_hatch_key": req.piece.leg_base_hatch_key,
        }
    return {}


def build_section_knowledge(req: SectionViewRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    piece = _resolve_piece_envelope(req)
    ergo_envelope = _ergonomic_lookup(piece.get("type", "")) if piece else {}

    # Tighter manufacturing slice — joinery + tolerances are what the
    # section drawing actually annotates.
    joinery_pack = {k: dict(v) for k, v in manufacturing.JOINERY.items()}

    # Material envelopes the layer stack draws on.
    material_envelopes = {
        "wood_brd": {
            "ranges": materials.WOOD_BRD_RANGES,
            "finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
        },
        "foam_brd": dict(materials.FOAM_BRD_SPEC),
        "upholstery_leather_brd": dict(materials.UPHOLSTERY_LEATHER_BRD_SPEC),
        "upholstery_fabric_brd": dict(materials.UPHOLSTERY_FABRIC_BRD_SPEC),
        "upholstery_durability_min_rubs_k": materials.UPHOLSTERY_DURABILITY_BRD["commercial_min_k"],
    }

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "material_palette": pack.get("material_palette", {}),
            "signature_moves": pack.get("signature_moves", []),
            "ergonomic_intent": pack.get("ergonomic_intent"),
        },
        "piece_envelope": piece,
        "ergonomic_envelope_mm": ergo_envelope,
        "joinery_catalogue": joinery_pack,
        "tolerances_mm": {k: v["+-mm"] for k, v in manufacturing.TOLERANCES.items()},
        "material_envelopes": material_envelopes,
        "scale_options": list(section_view.SECTION_SCALE_OPTIONS),
        "joinery_keys_in_scope": list(section_view.JOINERY_KEYS),
        "reinforcement_types_in_scope": list(section_view.REINFORCEMENT_TYPES),
        "hatch_vocabulary": list(section_view.HATCH_PATTERNS.keys()),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


SECTION_AUTHOR_SYSTEM_PROMPT = """You are an architectural draftsperson preparing the *section view* sheet — the cut-through page that explains the internal construction of a piece. You decide which layers stack inside, which joints hold it together, where reinforcement sits, what seat depth and back angle resolve to, and how the leg tapers.

Read the [KNOWLEDGE] block — piece envelope, ergonomic envelope, joinery catalogue + tolerances, BRD material envelopes (wood / foam / leather / fabric), scale + hatch vocabularies — and produce a structured section_view_spec covering five things:

  1. Cut + view target  — cut_label (e.g. A-A) and view_target (through_seat / through_arm / through_leg / through_back).
  2. Scale              — pick from scale_options; 1:5 / 1:10 for furniture-scale, 1:20 for larger pieces.
  3. Layer stack        — internal_layers[] from outer (fabric) inward (foam → frame → support); each {label, hatch_key, thickness_mm, source}.
  4. Joints + reinforcement — joints[] with joinery key from joinery_keys_in_scope and {x_ratio, y_ratio} positions; reinforcement[] with type from reinforcement_types_in_scope.
  5. Key dimensions     — key_dimensions_mm.seat_depth_mm + back_angle_deg + leg_taper_mm {top, bottom}; back_angle in degrees from vertical (mid-century lounge typically 100–108° from horizontal seat → ~10–18° back tilt).

Hard rules:
- scale MUST be in scale_options.
- Each joint.joinery MUST be in joinery_keys_in_scope.
- Each reinforcement.type MUST be in reinforcement_types_in_scope.
- Each hatch_key MUST be in hatch_vocabulary.
- seat_depth_mm MUST fall inside ergonomic_envelope_mm.seat_depth_mm band when present.
- back_angle_deg MUST be a positive number under 30 (degrees from vertical).
- foam thickness MUST come from a defensible source (cite HD36 / HR40 / memory_foam from foam_brd note); leather thickness from leather_brd.thickness_mm 1.2–1.5; fabric typically a thin layer (3–5 mm with backing).
- All x_ratio / y_ratio in [0, 1] — y_ratio=0 is floor, 1 is top.
- Studio voice — short, technical, decisive."""


SECTION_VIEW_SCHEMA: dict[str, Any] = {
    "name": "section_view_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sheet_narrative": {"type": "string"},
            "cut_label": {"type": "string"},
            "view_target": {"type": "string"},
            "scale": {"type": "string"},
            "scale_rationale": {"type": "string"},
            "layer_origin": {"type": "string"},  # top | bottom | full
            "internal_layers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "hatch_key": {"type": "string"},
                        "thickness_mm": {"type": "number"},
                        "source": {"type": "string"},
                    },
                    "required": ["label", "hatch_key", "thickness_mm", "source"],
                    "additionalProperties": False,
                },
            },
            "joints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "joinery": {"type": "string"},
                        "x_ratio": {"type": "number"},
                        "y_ratio": {"type": "number"},
                        "tolerance_mm": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "joinery", "x_ratio", "y_ratio", "tolerance_mm", "rationale"],
                    "additionalProperties": False,
                },
            },
            "reinforcement": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "type": {"type": "string"},
                        "x_ratio": {"type": "number"},
                        "y_ratio": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "type", "x_ratio", "y_ratio", "rationale"],
                    "additionalProperties": False,
                },
            },
            "key_dimensions_mm": {
                "type": "object",
                "properties": {
                    "seat_depth_mm": {"type": "number"},
                    "back_height_mm": {"type": "number"},
                    "arm_height_mm": {"type": "number"},
                },
                "required": ["seat_depth_mm", "back_height_mm", "arm_height_mm"],
                "additionalProperties": False,
            },
            "back_angle_deg": {"type": "number"},
            "leg_taper_mm": {
                "type": "object",
                "properties": {
                    "top": {"type": "number"},
                    "bottom": {"type": "number"},
                },
                "required": ["top", "bottom"],
                "additionalProperties": False,
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "sheet_narrative",
            "cut_label",
            "view_target",
            "scale",
            "scale_rationale",
            "layer_origin",
            "internal_layers",
            "joints",
            "reinforcement",
            "key_dimensions_mm",
            "back_angle_deg",
            "leg_taper_mm",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: SectionViewRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Cut label (from plan): {req.cut_label}\n"
        f"- View target: {req.view_target}\n"
        f"- Sheet title: {req.sheet_title}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the section_view_spec JSON. The cut shows the inside of the piece — call out "
        "every meaningful layer, every joint, every reinforcement. Pin seat depth, back angle, "
        "and leg taper. Cite real BRD numbers (foam grade, leather thickness, joinery tolerance)."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _within_band(value: float, band: Any) -> bool:
    if not isinstance(band, tuple) or len(band) != 2:
        return True
    return float(band[0]) - 1.0 <= value <= float(band[1]) + 1.0


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    scale_ok = spec.get("scale") in knowledge.get("scale_options", [])
    joinery_vocab = set(knowledge.get("joinery_keys_in_scope", []))
    reinf_vocab = set(knowledge.get("reinforcement_types_in_scope", []))
    hatch_vocab = set(knowledge.get("hatch_vocabulary", []))

    bad_joinery = [j.get("joinery") for j in (spec.get("joints") or []) if j.get("joinery") not in joinery_vocab]
    bad_reinf = [r.get("type") for r in (spec.get("reinforcement") or []) if r.get("type") not in reinf_vocab]
    bad_hatches = [l.get("hatch_key") for l in (spec.get("internal_layers") or []) if l.get("hatch_key") not in hatch_vocab]

    bad_ratios: list[str] = []
    for c in (spec.get("joints") or []) + (spec.get("reinforcement") or []):
        x = c.get("x_ratio")
        y = c.get("y_ratio")
        if x is None or not (0.0 <= float(x) <= 1.0):
            bad_ratios.append(f"{c.get('key')}.x_ratio")
        if y is None or not (0.0 <= float(y) <= 1.0):
            bad_ratios.append(f"{c.get('key')}.y_ratio")

    seat_depth = (spec.get("key_dimensions_mm") or {}).get("seat_depth_mm")
    seat_depth_band = (knowledge.get("ergonomic_envelope_mm") or {}).get("seat_depth_mm")
    seat_depth_ok = seat_depth is None or _within_band(float(seat_depth), seat_depth_band)

    back_angle = spec.get("back_angle_deg")
    back_angle_ok = back_angle is None or (0.0 < float(back_angle) < 30.0)

    return {
        "scale_in_catalogue": scale_ok,
        "joinery_vocab_valid": not bad_joinery,
        "bad_joinery": bad_joinery,
        "reinforcement_vocab_valid": not bad_reinf,
        "bad_reinforcement": bad_reinf,
        "hatch_vocab_valid": not bad_hatches,
        "bad_hatch_keys": bad_hatches,
        "callout_ratios_valid": not bad_ratios,
        "bad_ratios": bad_ratios,
        "seat_depth_in_envelope": seat_depth_ok,
        "seat_depth_envelope_mm": seat_depth_band,
        "back_angle_in_range": back_angle_ok,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class SectionViewError(RuntimeError):
    """Raised when the LLM section stage cannot produce a grounded spec."""


async def generate_section_view_drawing(req: SectionViewRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise SectionViewError(
            "OpenAI API key is not configured. The section-view stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_section_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise SectionViewError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the drawing."
        )
    if not knowledge.get("piece_envelope"):
        raise SectionViewError(
            "No piece envelope supplied; section view requires an explicit piece to cut through."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SECTION_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": SECTION_VIEW_SCHEMA,
            },
            temperature=0.3,
            max_tokens=2200,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for section-view drawing")
        raise SectionViewError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SectionViewError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    rendered = section_view.render_section_view(
        piece=knowledge.get("piece_envelope"),
        section_spec=spec,
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
        sheet_title=req.sheet_title,
    )

    return {
        "id": "section_view",
        "name": "Section View",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "section_view_spec": spec,
        "svg": rendered["svg"],
        "validation": validation,
        "meta": {
            **rendered.get("meta", {}),
            "layer_count_specced": len(spec.get("internal_layers", [])),
            "joint_count_specced": len(spec.get("joints", [])),
            "reinforcement_count_specced": len(spec.get("reinforcement", [])),
        },
    }
