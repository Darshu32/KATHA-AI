"""LLM-driven Volumetric (Block) diagram service (BRD Layer 2B #4).

Distinct from the Volumetric Hierarchy sheet (BRD 2B #3, which reads
weight + space-allocation). This sheet is the pure block / void
reading — what mass exists, where the voids sit, and how the volumes
relate to each other in space.

Pipeline contract:

    INPUT (parametric spec or design graph + theme)
      → INJECT  (object envelope summary + adjacency clues +
                 slicing-plane catalogue + theme proportions)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic axonometric base + void/relationship overlays)
      → OUTPUT  (volumetric_block_spec JSON  +  annotated SVG)

The four BRD requirements:
  • 3D block representation
  • Void spaces highlighted
  • Spatial relationships clear
  • Generated from 3D model + slicing algorithm
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import themes
from app.services.diagrams import volumetric
from app.services.diagrams.svg_base import (
    ACCENT_COOL,
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER_DEEP,
    rect,
    text,
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


# ── Slicing-plane catalogue ─────────────────────────────────────────────────
# Bounded vocabulary for "slicing algorithm" — keeps LLM picks legal.
SLICING_PLANES = {
    "horizontal_floor_plan":     "Cut at floor; reads circulation + footprint.",
    "horizontal_eye_level":      "Cut at 1.5 m; reads furniture upper masses + voids between.",
    "horizontal_ceiling_plane":  "Cut just below ceiling; reads ceiling features + tall storage tops.",
    "vertical_long_section":     "Cut along the long axis; reads silhouette + level changes.",
    "vertical_short_section":    "Cut along the short axis; reads depth + back-to-front layering.",
    "axonometric_30_30":         "30° / 30° axo; reads block mass + spatial relationships in one shot.",
    "diagonal_quarter_cut":      "Quarter-cut from a corner; exposes interior of an enclosed mass.",
}

# Bounded vocabulary for spatial relationships.
RELATIONSHIP_TYPES = (
    "adjacency",      # two volumes touch
    "containment",    # one volume sits inside another
    "threshold",      # a void marks the transition
    "framing",        # two volumes frame a third
    "alignment",      # volumes share an axis or face
    "overlap",        # volumes share footprint at different levels
    "shadow_gap",     # two volumes sit close with a deliberate gap
)


# ── Request schema ──────────────────────────────────────────────────────────


class VolumetricBlockRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _summarise_objects(graph: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in graph.get("objects", [])[:40]:
        d = o.get("dimensions") or {}
        p = o.get("position") or {}
        out.append({
            "type": (o.get("type") or "").lower(),
            "name": o.get("name") or "",
            "position": {"x": p.get("x"), "y": p.get("y"), "z": p.get("z")},
            "dimensions_mm": {
                "length": d.get("length"),
                "width": d.get("width"),
                "height": d.get("height"),
            },
        })
    return out


def build_block_knowledge(req: VolumetricBlockRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    graph = req.design_graph or {}
    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "signature_moves": pack.get("signature_moves", []),
            "ergonomic_intent": pack.get("ergonomic_intent"),
        },
        "slicing_planes_in_scope": SLICING_PLANES,
        "relationship_types": list(RELATIONSHIP_TYPES),
        "graph_summary": {
            "object_count": len(graph.get("objects", [])),
            "objects": _summarise_objects(graph),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
        "parametric_geometry": (req.parametric_spec or {}).get("geometry") or {},
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


VOLUMETRIC_BLOCK_SYSTEM_PROMPT = """You are an architectural designer writing the *volumetric (block) diagram* sheet — the page that reads a project as solid masses, voids between them, and the spatial relationships those masses set up.

Read the [KNOWLEDGE] block — graph object envelopes, parametric geometry, theme proportions, slicing planes, relationship types — and commit to a structured spec covering four things:

  1. Block composition       — what the mass reads as (count + character of major blocks).
  2. Void spaces             — what voids exist between / inside the masses, and what each void is for.
  3. Spatial relationships   — pairs of masses (or mass + void) and the relationship_type that binds them.
  4. Slicing strategy        — pick one or two planes from slicing_planes_in_scope that best reveal the form, and say why.

Hard rules:
- Every relationship.type MUST be in relationship_types.
- Every slicing.plane_key MUST be in slicing_planes_in_scope.
- Reference real object names from graph_summary.objects; do not invent objects.
- Quantify dimensions in mm or m where the inputs allow.
- If a field is missing, name the assumption — never silently invent.
- Studio voice: short, technical, decisive. No filler."""


VOLUMETRIC_BLOCK_SCHEMA: dict[str, Any] = {
    "name": "volumetric_block_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "block_composition": {
                "type": "string",
                "description": "Two sentences: what the mass reads as as a 3D composition.",
            },
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "objects": {"type": "array", "items": {"type": "string"}},
                        "character": {"type": "string"},
                    },
                    "required": ["label", "objects", "character"],
                    "additionalProperties": False,
                },
            },
            "voids": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "between": {"type": "array", "items": {"type": "string"}},
                        "purpose": {"type": "string"},
                        "size_hint": {"type": "string"},
                    },
                    "required": ["label", "between", "purpose", "size_hint"],
                    "additionalProperties": False,
                },
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "type": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["from", "to", "type", "rationale"],
                    "additionalProperties": False,
                },
            },
            "slicing": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "plane_key": {"type": "string"},
                        "display_name": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["plane_key", "display_name", "rationale"],
                    "additionalProperties": False,
                },
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "block_composition",
            "blocks",
            "voids",
            "relationships",
            "slicing",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: VolumetricBlockRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the volumetric_block_spec JSON. Cluster objects into blocks, "
        "name the meaningful voids between them, identify relationships from "
        "relationship_types, and pick the slicing plane(s) that explain the form best."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    """Add block / void / relationship / slicing layers on top of the axo base."""
    composition = (spec.get("block_composition") or "").strip()
    blocks = spec.get("blocks") or []
    voids = spec.get("voids") or []
    rels = spec.get("relationships") or []
    slicing = spec.get("slicing") or []

    overlay_parts: list[str] = []

    # Top caption — block composition.
    if composition:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Block read: " + _wrap(composition, 110), size=11, fill=INK))

    # Right rail — voids + relationships.
    rail_w = 240
    rail_x = canvas_w - rail_w - 8
    rail_y = 130
    rail_h = max(160, 60 + 22 * (len(voids) + len(rels)))
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))

    cursor_y = rail_y + 18
    overlay_parts.append(text(rail_x + 12, cursor_y, "Voids", size=11, fill=INK, weight="600"))
    cursor_y += 16
    if voids:
        for v in voids[:5]:
            label = (v.get("label") or "").strip()
            size_hint = (v.get("size_hint") or "").strip()
            purpose = (v.get("purpose") or "").strip()
            overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_COOL, stroke="none"))
            overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(f"{label} — {size_hint}", 28), size=10, fill=INK, weight="600"))
            cursor_y += 12
            overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(purpose, 32), size=9, fill=INK_SOFT))
            cursor_y += 14
    else:
        overlay_parts.append(text(rail_x + 12, cursor_y, "(no voids reported)", size=9, fill=INK_MUTED))
        cursor_y += 16

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Relationships", size=11, fill=INK, weight="600"))
    cursor_y += 16
    for r in rels[:6]:
        label = f"{r.get('from')} ↔ {r.get('to')} ({r.get('type')})"
        overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_WARM, stroke="none"))
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(label, 32), size=10, fill=INK, weight="600"))
        cursor_y += 12
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(r.get("rationale") or "", 32), size=9, fill=INK_SOFT))
        cursor_y += 14

    # Block legend — left side.
    if blocks:
        leg_x = 40
        leg_y = canvas_h - 110
        overlay_parts.append(text(leg_x, leg_y, "Blocks", size=11, fill=INK, weight="600"))
        for i, b in enumerate(blocks[:5]):
            yy = leg_y + 16 + i * 14
            overlay_parts.append(rect(leg_x, yy - 8, 8, 8, fill=INK, stroke="none", opacity=0.85))
            overlay_parts.append(text(leg_x + 14, yy, _wrap(f"{b.get('label')}: {b.get('character')}", 70), size=9, fill=INK_SOFT))

    # Footer — slicing plane(s).
    if slicing:
        slices = " • ".join(
            f"{s.get('display_name', s.get('plane_key'))}: {s.get('rationale')}"
            for s in slicing[:2]
        )
        overlay_parts.append(text(40, canvas_h - 14, "Slicing: " + _wrap(slices, 130), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class VolumetricBlockError(RuntimeError):
    """Raised when the volumetric-block LLM stage cannot produce a grounded spec."""


async def generate_volumetric_block_diagram(req: VolumetricBlockRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise VolumetricBlockError(
            "OpenAI API key is not configured. The volumetric (block) diagram requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_block_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise VolumetricBlockError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": VOLUMETRIC_BLOCK_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": VOLUMETRIC_BLOCK_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for volumetric (block) diagram")
        raise VolumetricBlockError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VolumetricBlockError("LLM returned malformed JSON") from exc

    # Validation.
    bad_relationships = [
        r.get("type") for r in (spec.get("relationships") or [])
        if r.get("type") not in RELATIONSHIP_TYPES
    ]
    bad_slices = [
        s.get("plane_key") for s in (spec.get("slicing") or [])
        if s.get("plane_key") not in SLICING_PLANES
    ]
    validation = {
        "relationship_types_valid": not bad_relationships,
        "bad_relationships": bad_relationships,
        "slicing_planes_valid": not bad_slices,
        "bad_slicing_planes": bad_slices,
    }

    base = volumetric.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "volumetric_block",
        "name": "Volumetric Diagram",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "volumetric_block_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "block_count": len(spec.get("blocks", [])),
            "void_count": len(spec.get("voids", [])),
            "relationship_count": len(spec.get("relationships", [])),
        },
    }


def _stub_graph(req: VolumetricBlockRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
