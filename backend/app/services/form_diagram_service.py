"""LLM-driven Form Development diagram service (BRD Layer 2B #2).

Pipeline contract — same as the concept-transparency stage:

    INPUT (parametric spec or design graph + theme)
      → INJECT  (theme proportions / signature moves / variation flex
                 + zone taxonomy + parametric geometry)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic 4-stage panel + LLM annotations)
      → OUTPUT  (form_development_spec JSON  +  annotated SVG)

The LLM authors *the design moves* — what choice was made at each stage
and why. The deterministic renderer (form_development.py) plots the
4-panel evolution with the proportional grid and object footprints.
We splice the two together.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import themes, variations
from app.services.diagrams import form_development
from app.services.diagrams.svg_base import (
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


# ── Request schema ──────────────────────────────────────────────────────────


class FormDiagramRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=520, ge=240, le=1800)


# ── Knowledge slice the LLM gets ────────────────────────────────────────────


_GRID_SYSTEMS = {
    "rule_of_thirds": "3 × 3 (rule of thirds — neutral, default)",
    "golden_ratio": "Golden ratio (1.618 : 1) — classical proportion",
    "modular_repeat": "Modular repeat grid (e.g. 2 × 3 of equal bays)",
    "tatami_3x2": "3 × 2 tatami — horizontal-leaning, low-slung",
    "axial_5_zone": "5-zone axial (centre + 4 quadrants) — symmetric monumental",
}


def build_form_knowledge(req: FormDiagramRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    palette = pack.get("material_palette", {})
    graph = req.design_graph or {}
    primary_objects = [
        (o.get("type") or "").lower()
        for o in graph.get("objects", [])
        if (o.get("type") or "").lower() in {
            "sofa", "bed", "dining_table", "desk",
            "coffee_table", "wardrobe", "bookshelf", "kitchen_cabinet_base",
        }
    ]

    geom = (req.parametric_spec or {}).get("geometry") or {}

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "signature_moves": pack.get("signature_moves", []),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "material_palette": palette,
            "dos": pack.get("dos", []),
            "donts": pack.get("donts", []),
        },
        "grid_systems_in_scope": _GRID_SYSTEMS,
        "parametric_dimension_flex": variations.PARAMETRIC_DIMENSION_FLEX_PCT,
        "graph_summary": {
            "primary_objects": primary_objects,
            "object_count": len(graph.get("objects", [])),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
        "parametric_geometry": geom,
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


FORM_AUTHOR_SYSTEM_PROMPT = """You are a senior architectural designer writing the *form development* page of a project drawing set. You explain how the form arrived at its final state — not as marketing prose, but as a series of decisions a junior designer could replicate.

Read the [KNOWLEDGE] block — theme proportions, signature moves, parametric flex bands, parametric geometry, graph summary — and write a 4-stage form-development spec that mirrors the renderer's panels:

  Stage 01 Volume       — bounding mass, what the room or piece starts as
  Stage 02 Grid         — which proportional grid you overlay and why
  Stage 03 Subtract     — which footprints / voids carve into the volume
  Stage 04 Articulate   — which theme signature move closes the form

Hard rules:
- Every stage description is one decisive sentence — no filler.
- The grid system you cite MUST be a key in grid_systems_in_scope.
- Signature moves you cite MUST be in theme.signature_moves.
- Cite real ratios / numbers when proportions or parametric_geometry give them to you.
- If a field is missing, name the assumption — never silently invent.
- Output is structured JSON conforming to the supplied schema.
"""


FORM_DIAGRAM_SCHEMA: dict[str, Any] = {
    "name": "form_development_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "form_summary": {
                "type": "string",
                "description": "Two sentences: the resolved form in plain language.",
            },
            "stages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "label": {"type": "string"},
                        "move": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["index", "label", "move", "rationale"],
                    "additionalProperties": False,
                },
            },
            "grid_system": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "display_name": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["key", "display_name", "rationale"],
                "additionalProperties": False,
            },
            "signature_moves_in_play": {
                "type": "array",
                "items": {"type": "string"},
            },
            "key_proportions": {
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
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "form_summary",
            "stages",
            "grid_system",
            "signature_moves_in_play",
            "key_proportions",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: FormDiagramRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the form_development_spec JSON. Four stages, exact grid system from the catalogue, "
        "signature moves only from the theme, and concrete proportions where they are present in the inputs."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    """Replace generic captions with LLM-authored stage annotations + grid label."""
    stages = spec.get("stages") or []
    grid = spec.get("grid_system") or {}
    summary = (spec.get("form_summary") or "").strip()
    sig = spec.get("signature_moves_in_play") or []

    overlay_parts: list[str] = []

    # Top caption strip — form summary.
    if summary:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, _wrap(summary, 130), size=11, fill=INK))

    # Per-stage captions sit below the panels; the base renderer already
    # writes generic ones at y = canvas_h - 30. We overwrite with LLM
    # annotations using a slightly higher y so both can coexist visually.
    panel_w = (canvas_w - 80) // 4
    if stages:
        for i, stage in enumerate(stages[:4]):
            cx = 40 + i * panel_w + panel_w // 2
            move = (stage.get("move") or "").strip()
            rationale = (stage.get("rationale") or "").strip()
            if move:
                overlay_parts.append(text(cx, canvas_h - 56, _wrap(move, 32), size=10, fill=INK, weight="600", anchor="middle"))
            if rationale:
                overlay_parts.append(text(cx, canvas_h - 42, _wrap(rationale, 36), size=9, fill=INK_SOFT, anchor="middle"))

    # Right-side grid + signature rail.
    rail_w = 200
    rail_x = canvas_w - rail_w - 8
    rail_y = 124
    rail_h = 92 + 14 * max(len(sig), 1)
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))
    overlay_parts.append(text(rail_x + 12, rail_y + 18, "Grid + signature", size=11, fill=INK, weight="600"))
    if grid:
        overlay_parts.append(text(rail_x + 12, rail_y + 36, "Grid: " + (grid.get("display_name") or grid.get("key") or "—"), size=10, fill=INK))
        if grid.get("rationale"):
            overlay_parts.append(text(rail_x + 12, rail_y + 50, _wrap(grid["rationale"], 30), size=9, fill=INK_SOFT))
    overlay_parts.append(text(rail_x + 12, rail_y + 76, "Moves in play:", size=10, fill=INK, weight="600"))
    for j, move in enumerate(sig[:4]):
        overlay_parts.append(text(rail_x + 12, rail_y + 92 + j * 14, "• " + _wrap(move, 28), size=9, fill=INK_SOFT))

    # Footer — key proportions if present.
    proportions = spec.get("key_proportions") or []
    if proportions:
        prop_text = " • ".join(f"{p.get('name')}={p.get('value')}" for p in proportions[:5])
        overlay_parts.append(text(40, canvas_h - 14, "Key proportions: " + _wrap(prop_text, 130), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class FormDiagramError(RuntimeError):
    """Raised when the LLM form stage cannot produce a grounded spec."""


async def generate_form_diagram(req: FormDiagramRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise FormDiagramError(
            "OpenAI API key is not configured. The form-development stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_form_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise FormDiagramError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": FORM_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": FORM_DIAGRAM_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for form-development diagram")
        raise FormDiagramError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FormDiagramError("LLM returned malformed JSON") from exc

    # Validate grid choice.
    grid_key = (spec.get("grid_system") or {}).get("key")
    grid_valid = grid_key in _GRID_SYSTEMS

    # Render base + annotate.
    base = form_development.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "form_development",
        "name": "Form Development",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "form_spec": spec,
        "svg": annotated_svg,
        "validation": {
            "grid_in_catalogue": grid_valid,
            "grid_key": grid_key,
        },
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "stage_count": len(spec.get("stages", [])),
            "signature_count": len(spec.get("signature_moves_in_play", [])),
        },
    }


def _stub_graph(req: FormDiagramRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": 2.7}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
