"""LLM-driven Elevation View drawing service (BRD Layer 3A #2).

Authors the *elevation_view_spec* — which heights to call out (seat, back,
overall, leg/base), which proportions to surface, where to place hardware
callouts, where to mark detail callouts — then hands it to the
deterministic elevation renderer.

Pipeline contract — same as the rest of the LLM services:

    INPUT (theme + (piece_envelope OR design graph) + parametric_spec)
      → INJECT  (ergonomic envelope + theme hardware/material rules +
                 scale & hatch catalogues + view options)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic elevation_view base with LLM-supplied spec)
      → OUTPUT  (elevation_view_spec JSON + technical SVG)

The five BRD requirements:
  • Height dimensions (seat, back, overall)
  • Leg/base proportions
  • Hardware placement
  • Detail callouts
  • Scale: 1:10 or 1:20
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import ergonomics, themes
from app.services.drawings import elevation_view

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


class ElevationPiece(BaseModel):
    type: str = Field(default="lounge_chair", max_length=64)
    dimensions_mm: dict[str, float] | None = None     # {length, width, height} in mm
    ergonomic_targets_mm: dict[str, float] | None = None  # seat_height_mm, back_height_mm, leg_base_mm, arm_height_mm
    material_hatch_key: str | None = None
    leg_base_hatch_key: str | None = None


class ElevationViewRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: ElevationPiece | None = None               # furniture-scale (preferred path)
    design_graph: dict[str, Any] | None = None        # room-scale fallback
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    view: str = Field(default="front", max_length=16)  # "front" or "side"
    sheet_title: str = Field(default="Elevation View", max_length=120)
    canvas_width: int = Field(default=1100, ge=480, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _ergonomic_lookup(piece_type: str) -> dict[str, Any]:
    t = (piece_type or "").lower()
    for table in (ergonomics.CHAIRS, ergonomics.TABLES, ergonomics.BEDS, ergonomics.STORAGE):
        if t in table:
            return {k: v for k, v in table[t].items()}
    return {}


def _resolve_piece_envelope(req: ElevationViewRequest) -> dict[str, Any]:
    if req.piece is not None:
        d = req.piece.dimensions_mm or {}
        e = req.piece.ergonomic_targets_mm or {}
        # Fall back to ergonomic envelope mid-points if dims absent.
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
                "back_height_mm": _midpoint(ergo.get("backrest_height_mm")),
                "arm_height_mm": _midpoint(ergo.get("arm_height_mm")),
                "leg_base_mm": 100 if "chair" in req.piece.type else None,
            }
            e = {k: v for k, v in e.items() if v is not None}
        return {
            "type": req.piece.type,
            "dimensions_mm": d,
            "ergonomic_targets_mm": e,
            "material_hatch_key": req.piece.material_hatch_key,
            "leg_base_hatch_key": req.piece.leg_base_hatch_key,
        }
    # Room-scale fallback from graph or parametric_spec geometry.
    geom = (req.parametric_spec or {}).get("geometry") or {}
    if geom.get("overall_height_mm"):
        return {
            "type": "room_wall",
            "dimensions_mm": {
                "length": geom.get("overall_length_mm") or 6000,
                "width": geom.get("overall_width_mm") or 4000,
                "height": geom.get("overall_height_mm") or 2700,
            },
            "ergonomic_targets_mm": {},
        }
    return {}


def _midpoint(rng: Any) -> float | None:
    if not rng or not isinstance(rng, tuple) or len(rng) != 2:
        return None
    return (float(rng[0]) + float(rng[1])) / 2.0


def build_elevation_knowledge(req: ElevationViewRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    piece = _resolve_piece_envelope(req)
    ergo_envelope = _ergonomic_lookup(piece.get("type", "")) if piece else {}

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "hardware": pack.get("hardware", {}),
            "material_palette": pack.get("material_palette", {}),
            "signature_moves": pack.get("signature_moves", []),
            "ergonomic_intent": pack.get("ergonomic_intent"),
        },
        "ergonomic_envelope_mm": ergo_envelope,
        "piece_envelope": piece,
        "scale_options": list(elevation_view.SCALE_OPTIONS),
        "view_options": list(elevation_view.VIEW_OPTIONS),
        "hatch_vocabulary": list(elevation_view.HATCH_PATTERNS.keys()),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


ELEVATION_AUTHOR_SYSTEM_PROMPT = """You are an architectural draftsperson preparing the *elevation view* sheet of a project drawing set. You decide which heights to call out, which proportions to surface, where the hardware sits, and which moments deserve a detail callout.

Read the [KNOWLEDGE] block — piece envelope (overall mm), ergonomic envelope (seat/back/arm ranges), theme proportions + hardware rules, scale + view + hatch catalogues — and write a structured elevation_view_spec covering five things:

  1. View          — 'front' or 'side'.
  2. Scale         — pick one from scale_options; 1:10 / 1:20 for furniture-scale.
  3. Heights       — height_dimensions[]: seat, back, arm, overall, leg/base; each as {label, from_mm, to_mm}.
  4. Hardware      — hardware_callouts[]: where the visible hardware sits (handle, hinge, leg cap), as {key, label, x_ratio 0..1, y_ratio 0..1}. y_ratio=0 is floor, 1 is top.
  5. Detail callouts — detail_callouts[]: what details warrant a closer drawing later, as {key, label, x_ratio, y_ratio}.

Plus:
  • proportions[]  — key visual ratios as {name, value}.

Hard rules:
- view MUST be in view_options.
- scale MUST be in scale_options.
- Each hardware_callouts and detail_callouts entry uses x_ratio AND y_ratio in [0, 1].
- Heights MUST come from / fall inside the ergonomic_envelope_mm bands when those bands exist.
- Hardware style MUST honour theme.hardware (e.g. if theme says "hidden or plinth-integrated", do not propose visible knobs on every door).
- Cite real mm values; no invented numbers outside the envelope.
- Studio voice — short, technical, decisive."""


ELEVATION_VIEW_SCHEMA: dict[str, Any] = {
    "name": "elevation_view_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sheet_narrative": {
                "type": "string",
                "description": "Two sentences: what this elevation emphasises.",
            },
            "view": {"type": "string"},
            "scale": {"type": "string"},
            "scale_rationale": {"type": "string"},
            "height_dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "from_mm": {"type": "number"},
                        "to_mm": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["label", "from_mm", "to_mm", "rationale"],
                    "additionalProperties": False,
                },
            },
            "width_dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "from_mm": {"type": "number"},
                        "to_mm": {"type": "number"},
                    },
                    "required": ["label", "from_mm", "to_mm"],
                    "additionalProperties": False,
                },
            },
            "proportions": {
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
            "hardware_callouts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                        "x_ratio": {"type": "number"},
                        "y_ratio": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["key", "label", "x_ratio", "y_ratio", "rationale"],
                    "additionalProperties": False,
                },
            },
            "detail_callouts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                        "x_ratio": {"type": "number"},
                        "y_ratio": {"type": "number"},
                        "what_to_detail": {"type": "string"},
                    },
                    "required": ["key", "label", "x_ratio", "y_ratio", "what_to_detail"],
                    "additionalProperties": False,
                },
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "sheet_narrative",
            "view",
            "scale",
            "scale_rationale",
            "height_dimensions",
            "width_dimensions",
            "proportions",
            "hardware_callouts",
            "detail_callouts",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: ElevationViewRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Requested view: {req.view}\n"
        f"- Sheet title: {req.sheet_title}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the elevation_view_spec JSON. Pick exactly one view + one scale. "
        "At minimum call out overall height + (where applicable) seat / back / arm / leg-base heights. "
        "Mark hardware only where the theme says hardware is visible. "
        "Tag at least one detail callout for the joint or moment that most needs a closer drawing."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _within_envelope(value_mm: float, band: Any) -> bool:
    if not isinstance(band, tuple) or len(band) != 2:
        return True  # no band → don't penalise
    lo, hi = float(band[0]), float(band[1])
    return lo - 1.0 <= value_mm <= hi + 1.0


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    scale_ok = spec.get("scale") in knowledge.get("scale_options", [])
    view_ok = spec.get("view") in knowledge.get("view_options", [])
    ergo = knowledge.get("ergonomic_envelope_mm") or {}

    # Spot-check seat / back / arm if they appear in the spec by label.
    out_of_envelope: list[dict[str, Any]] = []
    for d in spec.get("height_dimensions") or []:
        label_l = (d.get("label") or "").lower()
        height_mm = float(d.get("to_mm") or 0) - float(d.get("from_mm") or 0)
        if "seat" in label_l and "seat_height_mm" in ergo and not _within_envelope(height_mm, ergo["seat_height_mm"]):
            out_of_envelope.append({"label": d.get("label"), "value_mm": height_mm, "envelope": ergo["seat_height_mm"]})
        if "back" in label_l and "backrest_height_mm" in ergo and not _within_envelope(height_mm, ergo["backrest_height_mm"]):
            out_of_envelope.append({"label": d.get("label"), "value_mm": height_mm, "envelope": ergo["backrest_height_mm"]})
        if "arm" in label_l and "arm_height_mm" in ergo and not _within_envelope(height_mm, ergo["arm_height_mm"]):
            out_of_envelope.append({"label": d.get("label"), "value_mm": height_mm, "envelope": ergo["arm_height_mm"]})

    bad_ratios: list[str] = []
    for c in (spec.get("hardware_callouts") or []) + (spec.get("detail_callouts") or []):
        x = c.get("x_ratio")
        y = c.get("y_ratio")
        if x is None or not (0.0 <= float(x) <= 1.0):
            bad_ratios.append(f"{c.get('key')}.x_ratio")
        if y is None or not (0.0 <= float(y) <= 1.0):
            bad_ratios.append(f"{c.get('key')}.y_ratio")

    return {
        "scale_in_catalogue": scale_ok,
        "view_in_catalogue": view_ok,
        "heights_in_envelope": not out_of_envelope,
        "out_of_envelope": out_of_envelope,
        "callout_ratios_valid": not bad_ratios,
        "bad_ratios": bad_ratios,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class ElevationViewError(RuntimeError):
    """Raised when the LLM elevation stage cannot produce a grounded spec."""


async def generate_elevation_view_drawing(req: ElevationViewRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ElevationViewError(
            "OpenAI API key is not configured. The elevation-view stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_elevation_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise ElevationViewError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the drawing."
        )
    if not knowledge.get("piece_envelope"):
        raise ElevationViewError(
            "No piece envelope or design graph supplied; cannot project an elevation."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": ELEVATION_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ELEVATION_VIEW_SCHEMA,
            },
            temperature=0.3,
            max_tokens=1800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for elevation-view drawing")
        raise ElevationViewError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ElevationViewError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    rendered = elevation_view.render_elevation_view(
        piece=knowledge.get("piece_envelope"),
        graph=req.design_graph,
        elevation_spec=spec,
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
        sheet_title=req.sheet_title,
    )

    return {
        "id": "elevation_view",
        "name": "Elevation View",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "elevation_view_spec": spec,
        "svg": rendered["svg"],
        "validation": validation,
        "meta": {
            **rendered.get("meta", {}),
            "height_dim_specced": len(spec.get("height_dimensions", [])),
            "width_dim_specced": len(spec.get("width_dimensions", [])),
            "hardware_count": len(spec.get("hardware_callouts", [])),
            "detail_count": len(spec.get("detail_callouts", [])),
        },
    }
