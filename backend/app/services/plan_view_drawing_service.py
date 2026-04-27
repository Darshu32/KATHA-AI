"""LLM-driven Plan View drawing service (BRD Layer 3A #1).

Authors the *plan_view_spec* — which dimensions to call out, where to
cut sections, which hatch to use per material zone, what scale to
adopt — then hands it to the deterministic plan_view renderer.

Pipeline contract (same as 2B services):

    INPUT (theme + design graph + parametric_spec)
      → INJECT  (graph object envelope + theme palette + scale options +
                 hatch vocabulary + dimension/section reference catalogue)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic plan_view base with LLM-supplied plan_spec)
      → OUTPUT  (plan_view_spec JSON + technical SVG)

The five BRD requirements:
  • Overall dimensions (width × depth)
  • Key measurements annotated
  • Section reference lines
  • Material zones (hatching)
  • Scale: 1:10 or 1:20 (extends to 1:50 / 1:100 for room plans)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import themes
from app.services.drawings import plan_view

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


class PlanViewRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    sheet_title: str = Field(default="Plan View", max_length=120)
    canvas_width: int = Field(default=1100, ge=480, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_plan_knowledge(req: PlanViewRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    palette = pack.get("material_palette", {})
    graph = req.design_graph or {}
    objects = graph.get("objects", [])

    object_summary = []
    for o in objects[:30]:
        d = o.get("dimensions") or {}
        p = o.get("position") or {}
        object_summary.append({
            "type": (o.get("type") or "").lower(),
            "name": o.get("name") or "",
            "position": {"x": p.get("x"), "z": p.get("z")},
            "dimensions_m": {"length": d.get("length"), "width": d.get("width"), "height": d.get("height")},
        })

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "material_palette": palette,
            "signature_moves": pack.get("signature_moves", []),
        },
        "scale_options": list(plan_view.SCALE_OPTIONS),
        "hatch_vocabulary": list(plan_view.HATCH_PATTERNS.keys()),
        "graph_summary": {
            "object_count": len(objects),
            "objects": object_summary,
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


PLAN_AUTHOR_SYSTEM_PROMPT = """You are an architectural draftsperson preparing the *plan view* sheet of a project drawing set. You decide what to dimension, where to cut sections, which hatch to assign per material zone, and what scale fits the sheet.

Read the [KNOWLEDGE] block and produce a structured plan_view_spec covering five things:

  1. Scale          — pick one from scale_options (1:10 / 1:20 for piece-scale, 1:50 / 1:100 for room-scale).
  2. Key dimensions — what overall and intermediate dimensions to call out (label + axis).
  3. Section refs   — at least one section line; bubble label (A, B, ...), axis, normalised position 0..1.
  4. Material zones — for each object_type that has a meaningful material reading, pick one hatch_key from hatch_vocabulary.
  5. Sheet narrative — two-sentence designer's note on what this plan emphasises.

Hard rules:
- scale MUST be in scale_options.
- Each material_zones[i].hatch_key MUST be in hatch_vocabulary.
- Each material_zones[i].object_type MUST exist in graph_summary.objects.
- Each section_reference.position is a float 0..1 along the chosen axis.
- Cite real dimensions in metres (overall length × width = the room dimensions).
- Studio voice — short, technical, decisive."""


PLAN_VIEW_SCHEMA: dict[str, Any] = {
    "name": "plan_view_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sheet_narrative": {
                "type": "string",
                "description": "Two sentences: what this plan view emphasises.",
            },
            "scale": {
                "type": "string",
                "description": "One of scale_options.",
            },
            "scale_rationale": {
                "type": "string",
            },
            "key_dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "axis": {"type": "string"},      # "x" or "z"
                        "value_m": {"type": "number"},
                    },
                    "required": ["label", "axis", "value_m"],
                    "additionalProperties": False,
                },
            },
            "section_references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "axis": {"type": "string"},      # "x" cuts vertically, "z" cuts horizontally
                        "position": {"type": "number"},  # 0..1
                        "rationale": {"type": "string"},
                    },
                    "required": ["label", "axis", "position", "rationale"],
                    "additionalProperties": False,
                },
            },
            "material_zones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "hatch_key": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["object_type", "hatch_key", "rationale"],
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
            "scale",
            "scale_rationale",
            "key_dimensions",
            "section_references",
            "material_zones",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: PlanViewRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Sheet title: {req.sheet_title}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the plan_view_spec JSON. Pick exactly one scale. "
        "Call out at least the overall length × width as key dimensions, plus any "
        "interior dimensions worth noting. Mark at least one section reference. "
        "Assign hatches only to objects whose material reading benefits from one."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    scale_ok = spec.get("scale") in knowledge.get("scale_options", [])
    hatch_vocab = set(knowledge.get("hatch_vocabulary", []))
    graph_types = {o.get("type") for o in knowledge.get("graph_summary", {}).get("objects", [])}

    bad_hatches: list[str] = []
    bad_zone_types: list[str] = []
    for z in spec.get("material_zones") or []:
        if (z.get("hatch_key") or "").lower() not in hatch_vocab:
            bad_hatches.append(z.get("hatch_key"))
        if (z.get("object_type") or "").lower() not in graph_types:
            bad_zone_types.append(z.get("object_type"))

    out_of_range_sections: list[str] = []
    for s in spec.get("section_references") or []:
        pos = s.get("position")
        if pos is None or not (0.0 <= float(pos) <= 1.0) or s.get("axis") not in ("x", "z"):
            out_of_range_sections.append(s.get("label"))

    return {
        "scale_in_catalogue": scale_ok,
        "hatch_vocab_valid": not bad_hatches,
        "bad_hatch_keys": bad_hatches,
        "material_zone_object_types_valid": not bad_zone_types,
        "bad_zone_object_types": bad_zone_types,
        "section_references_valid": not out_of_range_sections,
        "bad_section_references": out_of_range_sections,
    }


# ── Public API ──────────────────────────────────────────────────────────────


class PlanViewError(RuntimeError):
    """Raised when the LLM plan-view stage cannot produce a grounded spec."""


async def generate_plan_view_drawing(req: PlanViewRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise PlanViewError(
            "OpenAI API key is not configured. The plan-view stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_plan_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise PlanViewError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the drawing."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": PLAN_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": PLAN_VIEW_SCHEMA,
            },
            temperature=0.3,
            max_tokens=1600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for plan-view drawing")
        raise PlanViewError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanViewError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    rendered = plan_view.render_plan_view(
        graph=req.design_graph or _stub_graph(req),
        plan_spec=spec,
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
        sheet_title=req.sheet_title,
    )

    return {
        "id": "plan_view",
        "name": "Plan View",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "plan_view_spec": spec,
        "svg": rendered["svg"],
        "validation": validation,
        "meta": {
            **rendered.get("meta", {}),
            "key_dimension_count": len(spec.get("key_dimensions", [])),
            "section_count": len(spec.get("section_references", [])),
            "hatch_count": len(spec.get("material_zones", [])),
        },
    }


def _stub_graph(req: PlanViewRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
