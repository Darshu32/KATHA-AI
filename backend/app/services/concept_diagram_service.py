"""LLM-driven Concept Transparency diagram service (BRD Layer 2B #1).

Pipeline contract:

    INPUT (parametric spec or design graph + theme)
      → INJECT  (theme rule pack + zone rules + parametric proportions /
                 material palette / signature moves)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic SVG annotated with LLM concept spec)
      → OUTPUT (concept_transparency_spec JSON  +  annotated SVG)

Why split LLM and renderer? The geometry of a plan diagram is mechanical
— rectangles, scale, palette colours from the theme. The *meaning* of
the diagram (what each zone says, why a material is paired with a form,
which moments to emphasise) is creative reasoning that needs the LLM.
We let the LLM author the concept; we let pure code draw it.
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
from app.services.diagrams import concept_transparency
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


class ConceptDiagramRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=320, le=2400)
    canvas_height: int = Field(default=600, ge=240, le=1800)


# ── Knowledge slice the LLM gets ────────────────────────────────────────────


def build_concept_knowledge(req: ConceptDiagramRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    palette = pack.get("material_palette", {})
    graph = req.design_graph or {}
    object_types = sorted({(o.get("type") or "").lower() for o in graph.get("objects", []) if o.get("type")})

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "material_palette": palette,
            "colour_palette": pack.get("colour_palette", []),
            "colour_strategy": pack.get("colour_strategy"),
            "material_pattern": pack.get("material_pattern", {}),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
            "dos": pack.get("dos", []),
            "donts": pack.get("donts", []),
        },
        "zone_taxonomy": dict(concept_transparency.ZONE_RULES),
        "graph_summary": {
            "object_types_present": object_types,
            "object_count": len(graph.get("objects", [])),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
        "parametric_spec": req.parametric_spec or None,
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


CONCEPT_AUTHOR_SYSTEM_PROMPT = """You are an architecture diagram author at a working studio. Your job is to write the *concept transparency layer* of a project — the short, decisive prose that turns a plan into a story a client understands at a glance.

Read the [KNOWLEDGE] block — theme rule pack, zone taxonomy, parametric spec, design graph summary — and commit to a concept.

Hard rules:
- Every zone you describe MUST be a key in zone_taxonomy. Do not invent zones.
- Materials you reference MUST come from theme.material_palette or parametric_spec.wood_spec / hardware_spec. No hallucinated materials.
- Cite the theme's signature_moves where they apply. Do not invent moves.
- If a field is missing from the inputs, name the assumption — do not silently fill it.
- Studio cadence: 1–3 short sentences per field, technical, decisive. No marketing prose.
- Output is structured JSON conforming to the supplied schema."""


CONCEPT_DIAGRAM_SCHEMA: dict[str, Any] = {
    "name": "concept_transparency_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "design_intent": {
                "type": "string",
                "description": "Two sentences: the core idea the design is trying to deliver.",
            },
            "material_form_relationship": {
                "type": "string",
                "description": "How the chosen materials and the chosen forms reinforce each other.",
            },
            "zone_assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "zone": {"type": "string"},
                        "label": {"type": "string"},
                        "dominant_material": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["zone", "label", "dominant_material", "rationale"],
                    "additionalProperties": False,
                },
            },
            "emphasis_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "description"],
                    "additionalProperties": False,
                },
            },
            "signature_moves_in_play": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "design_intent",
            "material_form_relationship",
            "zone_assignments",
            "emphasis_points",
            "signature_moves_in_play",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: ConceptDiagramRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the concept_transparency_spec JSON. Use only the zones, materials, "
        "and signature moves present in the knowledge block. Be specific."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(base_svg: str, spec: dict[str, Any], canvas_w: int, canvas_h: int) -> str:
    """Inject the LLM concept spec into the deterministic base SVG.

    Adds (a) a design-intent caption strip across the top of the canvas
    and (b) a right-side rationale rail listing zone assignments — both
    rendered with the same INK / PAPER palette as the base diagram.
    """
    intent = (spec or {}).get("design_intent", "").strip()
    relationship = (spec or {}).get("material_form_relationship", "").strip()
    zones = (spec or {}).get("zone_assignments", []) or []

    overlay_parts: list[str] = []

    # Caption strip — sits between title block (y=40) and the plan.
    if intent:
        overlay_parts.append(rect(40, 90, canvas_w - 80, 36, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 112, _wrap(intent, 110), size=11, fill=INK))

    # Right-side rail — zone rationales.
    rail_x = canvas_w - 220
    rail_w = 200
    rail_y = 140
    rail_h = max(120, 24 + 44 * len(zones))
    if zones:
        overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))
        overlay_parts.append(text(rail_x + 12, rail_y + 20, "Concept zones", size=11, fill=INK, weight="600"))
        for i, z in enumerate(zones[:6]):
            row_y = rail_y + 40 + i * 44
            label = (z.get("label") or z.get("zone") or "").strip()
            mat = (z.get("dominant_material") or "").strip()
            rationale = (z.get("rationale") or "").strip()
            overlay_parts.append(text(rail_x + 12, row_y, f"{label} — {mat}", size=10, fill=INK, weight="600"))
            overlay_parts.append(text(rail_x + 12, row_y + 14, _wrap(rationale, 30), size=9, fill=INK_SOFT))

    # Footer — material/form relationship.
    if relationship:
        overlay_parts.append(text(40, canvas_h - 18, "Material × form: " + _wrap(relationship, 130), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    # Inject before closing </svg>.
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    """Plain truncate-with-ellipsis (SVG single-line text). Real wrapping
    would need <tspan>; keeping this simple for now."""
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class ConceptDiagramError(RuntimeError):
    """Raised when the LLM concept stage cannot produce a grounded spec."""


async def generate_concept_diagram(req: ConceptDiagramRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ConceptDiagramError(
            "OpenAI API key is not configured. The concept-transparency stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_concept_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise ConceptDiagramError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": CONCEPT_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": CONCEPT_DIAGRAM_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for concept diagram")
        raise ConceptDiagramError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConceptDiagramError("LLM returned malformed JSON") from exc

    # Render the deterministic base diagram from the (possibly empty) graph.
    base = concept_transparency.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "concept_transparency",
        "name": "Concept Transparency",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "concept_spec": spec,
        "svg": annotated_svg,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "zone_count": len(spec.get("zone_assignments", [])),
            "emphasis_count": len(spec.get("emphasis_points", [])),
        },
    }


def _stub_graph(req: ConceptDiagramRequest) -> dict[str, Any]:
    """Minimal graph so the renderer has something to plot when only a
    parametric spec is supplied. Pulls room dims from the parametric
    spec.geometry where available."""
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": 2.7}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
