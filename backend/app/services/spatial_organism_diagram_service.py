"""LLM-driven Spatial Organism diagram (BRD Layer 2B #7).

Reads the design as something a body inhabits — not as a layout, but as
a sequence of human interactions and movements. Combines the
deterministic plan + clearance halos from spatial_organism.py with an
LLM interpretation of usage patterns, interaction modes, and the
choreography of movement through the space.

Pipeline contract:

    INPUT (theme + design graph)
      → INJECT  (ergonomic targets per object type +
                 circulation clearances + interaction-mode catalogue +
                 movement-pattern catalogue + graph object summary)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic plan + circulation arrows + LLM overlay)
      → OUTPUT  (spatial_organism_spec JSON + annotated SVG)

The four BRD requirements:
  • How product inhabits space
  • Human interaction overlay
  • Movement patterns shown
  • Generated from ergonomic data + usage patterns
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import clearances, ergonomics, themes
from app.services.diagrams import spatial_organism
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


# ── Bounded vocabularies ────────────────────────────────────────────────────
INTERACTION_MODES = (
    "sit_relax",            # sofa / lounge chair
    "sit_focus",            # desk / dining
    "lie_rest",             # bed
    "stand_prepare",        # kitchen counter
    "stand_circulate",      # corridor / threshold
    "reach_retrieve",       # storage interaction
    "view_passive",         # tv / artwork facing
    "converse",             # face-to-face seating
)

MOVEMENT_PATTERNS = (
    "linear_spine",         # one main path end-to-end
    "loop",                 # path returns to origin
    "branch_T",             # main spine with branch
    "hub_and_spoke",        # central pivot, paths radiate
    "perimeter",            # path hugs the room edges
    "diagonal_cut",         # shortest diagonal across the room
)

USAGE_PATTERNS = (
    "single_user",          # one person at a time
    "intimate_pair",        # two people, close
    "small_group",          # 3-6 people
    "fluid_throughput",     # people pass through
    "multi_focus",          # two or more separate activity zones
)


# ── Request schema ──────────────────────────────────────────────────────────


class SpatialOrganismRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _ergonomic_lookup(obj_type: str) -> dict | None:
    t = (obj_type or "").lower()
    for table in (ergonomics.CHAIRS, ergonomics.TABLES, ergonomics.BEDS, ergonomics.STORAGE):
        if t in table:
            return {k: v for k, v in table[t].items()}
    return None


def _summarise_objects_for_organism(graph: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in graph.get("objects", [])[:30]:
        otype = (o.get("type") or "").lower()
        out.append({
            "type": otype,
            "name": o.get("name") or "",
            "ergonomic_envelope": _ergonomic_lookup(otype) or {},
            "position": o.get("position") or {},
        })
    return out


def build_organism_knowledge(req: SpatialOrganismRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    graph = req.design_graph or _stub_graph(req)
    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
        },
        "interaction_modes_in_scope": list(INTERACTION_MODES),
        "movement_patterns_in_scope": list(MOVEMENT_PATTERNS),
        "usage_patterns_in_scope": list(USAGE_PATTERNS),
        "circulation_thresholds_mm": {
            "around_bed_mm": clearances.CIRCULATION["around_bed"],
            "around_dining_table_mm": clearances.CIRCULATION["around_dining_table"],
            "in_front_of_sofa_mm": clearances.CIRCULATION["in_front_of_sofa"],
            "kitchen_walkway_single_mm": clearances.CIRCULATION["kitchen_walkway_single"],
            "kitchen_walkway_double_mm": clearances.CIRCULATION["kitchen_walkway_double"],
            "desk_pullout_mm": clearances.CIRCULATION["desk_pullout"],
            "wardrobe_opening_mm": clearances.CIRCULATION["wardrobe_opening"],
            "residential_corridor_min_mm": clearances.CORRIDORS["residential"]["min_width_mm"],
        },
        "graph_summary": {
            "object_count": len(graph.get("objects", [])),
            "objects": _summarise_objects_for_organism(graph),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


SPATIAL_ORGANISM_SYSTEM_PROMPT = """You are an architectural designer writing the *spatial organism* sheet — the page that explains how a body actually inhabits the space. Not the plan; the choreography.

Read the [KNOWLEDGE] block — ergonomic envelopes per object, circulation thresholds, theme ergonomic intent, interaction-mode / movement-pattern / usage-pattern catalogues, graph object summary — and produce a structured spec covering four things:

  1. Inhabitation summary       — the human read of the space in two sentences.
  2. Interaction touchpoints    — for each anchor object, name the interaction_mode + the body posture + the clearance involved.
  3. Movement choreography      — pick one movement_pattern + one usage_pattern, list the path stops in order.
  4. Watch-outs                 — pinch points, posture conflicts, missing clearances.

Hard rules:
- interaction_mode MUST be in interaction_modes_in_scope.
- movement_pattern MUST be in movement_patterns_in_scope.
- usage_pattern MUST be in usage_patterns_in_scope.
- Reference real object types from graph_summary.objects; do not invent objects.
- Cite real mm clearances from circulation_thresholds_mm.
- Studio voice — short, technical, decisive."""


SPATIAL_ORGANISM_SCHEMA: dict[str, Any] = {
    "name": "spatial_organism_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "inhabitation_summary": {
                "type": "string",
                "description": "Two sentences: how a body inhabits this space.",
            },
            "interaction_touchpoints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "interaction_mode": {"type": "string"},
                        "body_posture": {"type": "string"},
                        "clearance_mm": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "object_type",
                        "interaction_mode",
                        "body_posture",
                        "clearance_mm",
                        "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "movement_choreography": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "usage_pattern": {"type": "string"},
                    "path_stops": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["pattern", "usage_pattern", "path_stops", "rationale"],
                "additionalProperties": False,
            },
            "watchouts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["title", "detail"],
                    "additionalProperties": False,
                },
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "inhabitation_summary",
            "interaction_touchpoints",
            "movement_choreography",
            "watchouts",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: SpatialOrganismRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the spatial_organism_spec JSON. Cover every primary anchor object as a "
        "touchpoint. Pick exactly one movement_pattern and one usage_pattern. Reference "
        "real clearance mm from the catalogue."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    summary = (spec.get("inhabitation_summary") or "").strip()
    touchpoints = spec.get("interaction_touchpoints") or []
    movement = spec.get("movement_choreography") or {}
    wos = spec.get("watchouts") or []

    overlay_parts: list[str] = []

    # Top caption — inhabitation.
    if summary:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Inhabits: " + _wrap(summary, 110), size=11, fill=INK))

    # Right rail — touchpoints + movement + watch-outs.
    rail_w = 240
    rail_x = canvas_w - rail_w - 8
    rail_y = 130
    rail_h = max(220, 64 + 30 * (len(touchpoints) + len(wos) + 2))
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))

    cursor_y = rail_y + 18
    overlay_parts.append(text(rail_x + 12, cursor_y, "Interaction touchpoints", size=11, fill=INK, weight="600"))
    cursor_y += 16
    for t in touchpoints[:6]:
        overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_WARM, stroke="none"))
        head = f"{t.get('object_type')} — {t.get('interaction_mode')}"
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(head, 28), size=10, fill=INK, weight="600"))
        cursor_y += 12
        body = f"{t.get('body_posture')}; clearance {t.get('clearance_mm')}mm"
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(body, 32), size=9, fill=INK_SOFT))
        cursor_y += 14

    # Movement choreography block.
    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Movement", size=11, fill=INK, weight="600"))
    cursor_y += 16
    overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_COOL, stroke="none"))
    move_head = f"{movement.get('pattern')} • {movement.get('usage_pattern')}"
    overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(move_head, 28), size=10, fill=INK, weight="600"))
    cursor_y += 12
    stops = movement.get("path_stops") or []
    if stops:
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(" → ".join(stops), 32), size=9, fill=INK_SOFT))
        cursor_y += 14
    if movement.get("rationale"):
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(movement["rationale"], 32), size=9, fill=INK_SOFT))
        cursor_y += 14

    # Watch-outs.
    if wos:
        cursor_y += 6
        overlay_parts.append(text(rail_x + 12, cursor_y, "Watch-outs", size=11, fill=INK, weight="600"))
        cursor_y += 14
        for w in wos[:4]:
            overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill="#7a4632", stroke="none"))
            overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(w.get("title") or "", 28), size=10, fill=INK, weight="600"))
            cursor_y += 12
            overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(w.get("detail") or "", 32), size=9, fill=INK_SOFT))
            cursor_y += 14

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class SpatialOrganismError(RuntimeError):
    """Raised when the LLM spatial-organism stage cannot produce a grounded spec."""


async def generate_spatial_organism_diagram(req: SpatialOrganismRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise SpatialOrganismError(
            "OpenAI API key is not configured. The spatial-organism stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_organism_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise SpatialOrganismError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SPATIAL_ORGANISM_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": SPATIAL_ORGANISM_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for spatial-organism diagram")
        raise SpatialOrganismError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SpatialOrganismError("LLM returned malformed JSON") from exc

    # Validation — bounded vocabularies.
    bad_modes = [t.get("interaction_mode") for t in (spec.get("interaction_touchpoints") or []) if t.get("interaction_mode") not in INTERACTION_MODES]
    movement_pattern = (spec.get("movement_choreography") or {}).get("pattern")
    usage_pattern = (spec.get("movement_choreography") or {}).get("usage_pattern")
    validation = {
        "interaction_modes_valid": not bad_modes,
        "bad_interaction_modes": bad_modes,
        "movement_pattern_valid": movement_pattern in MOVEMENT_PATTERNS,
        "usage_pattern_valid": usage_pattern in USAGE_PATTERNS,
    }

    base = spatial_organism.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "spatial_organism",
        "name": "Spatial Organism",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "spatial_organism_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "touchpoint_count": len(spec.get("interaction_touchpoints", [])),
            "watchout_count": len(spec.get("watchouts", [])),
            "movement_pattern": movement_pattern,
            "usage_pattern": usage_pattern,
        },
    }


def _stub_graph(req: SpatialOrganismRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
