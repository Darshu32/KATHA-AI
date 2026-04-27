"""LLM-driven Solid vs Void diagram (BRD Layer 2B #6).

Reads the plan as positive (solid) and negative (void) space — answers
"how much room can the design breathe?" by combining the deterministic
geometry analysis (computed solid_pct / void_pct / breathing_m) with an
LLM interpretation of where weight concentrates and where the design
opens up.

Pipeline contract:

    INPUT (theme + design graph)
      → INJECT  (computed geometry stats from solid_void.py +
                 theme proportions + circulation thresholds)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic plan base + LLM interpretation overlay)
      → OUTPUT  (solid_void_spec JSON + annotated SVG)

The four BRD requirements:
  • Positive/negative space analysis
  • Visual weight distribution
  • Breathing room visualization
  • Generated from geometry analysis
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import clearances, themes
from app.services.diagrams import solid_void
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


# ── Bounded vocabulary ──────────────────────────────────────────────────────
WEIGHT_DISTRIBUTION_PATTERNS = (
    "centred_mass",      # solids cluster at the centre, voids ring the perimeter
    "perimeter_mass",    # solids hug the walls, central void
    "diagonal_split",    # solid on one diagonal, void on the other
    "linear_band",       # solids form a band; voids on either side
    "scattered",         # no clear cluster — even distribution
    "asymmetric_lobe",   # one heavy lobe + opposite void
)

BREATHING_QUALITY = ("cramped", "tight", "comfortable", "generous", "over-scaled")


# ── Request schema ──────────────────────────────────────────────────────────


class SolidVoidRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _circulation_floor_mm(graph: dict[str, Any]) -> dict[str, int]:
    """Pick the circulation thresholds the LLM should compare breathing_m against."""
    return {
        "residential_corridor_min_mm": clearances.CORRIDORS["residential"]["min_width_mm"],
        "commercial_corridor_min_mm": clearances.CORRIDORS["commercial"]["min_width_mm"],
        "around_bed_mm": clearances.CIRCULATION["around_bed"],
        "around_dining_table_mm": clearances.CIRCULATION["around_dining_table"],
        "kitchen_walkway_double_mm": clearances.CIRCULATION["kitchen_walkway_double"],
    }


def build_solid_void_knowledge(req: SolidVoidRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    graph = req.design_graph or _stub_graph(req)

    # Run the deterministic geometry analysis first so the LLM gets real numbers.
    base_meta = solid_void.generate(graph, canvas_w=req.canvas_width, canvas_h=req.canvas_height).get("meta", {})

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
        },
        "computed_geometry": base_meta,        # solid_pct, void_pct, breathing_m, etc.
        "weight_distribution_patterns_in_scope": list(WEIGHT_DISTRIBUTION_PATTERNS),
        "breathing_quality_in_scope": list(BREATHING_QUALITY),
        "circulation_thresholds_mm": _circulation_floor_mm(graph),
        "graph_summary": {
            "object_count": len(graph.get("objects", [])),
            "object_types": sorted({(o.get("type") or "").lower() for o in graph.get("objects", []) if o.get("type")}),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


SOLID_VOID_SYSTEM_PROMPT = """You are an architectural designer writing the *solid vs void* sheet — the page that reads where the design has mass and where it has air, and whether the air is enough to breathe.

Read the [KNOWLEDGE] block — computed geometry stats (real solid/void percentages, breathing_m), theme proportions, circulation thresholds, weight-distribution patterns — and commit to a structured spec covering four things:

  1. Positive/negative space analysis — what the solid % and void % actually mean for this room.
  2. Visual weight distribution — pick one pattern from weight_distribution_patterns_in_scope and justify it.
  3. Breathing room — interpret breathing_m (in metres) against circulation_thresholds_mm; pick a quality from breathing_quality_in_scope.
  4. Watch-outs — pinch points, dead corners, over-scale issues that the percentages don't surface alone.

Hard rules:
- Cite the actual computed numbers from computed_geometry — do not invent.
- weight_distribution.pattern MUST be one of weight_distribution_patterns_in_scope.
- breathing_room.quality MUST be one of breathing_quality_in_scope.
- Compare breathing_m against the relevant threshold (residential ≥ 0.8 m, commercial ≥ 1.2 m, dining clearance 0.75 m, etc.).
- Studio voice — short, technical, decisive."""


SOLID_VOID_SCHEMA: dict[str, Any] = {
    "name": "solid_void_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "space_summary": {
                "type": "string",
                "description": "Two sentences: the positive/negative reading of this plan.",
            },
            "positive_negative_analysis": {
                "type": "object",
                "properties": {
                    "solid_pct": {"type": "number"},
                    "void_pct": {"type": "number"},
                    "interpretation": {"type": "string"},
                },
                "required": ["solid_pct", "void_pct", "interpretation"],
                "additionalProperties": False,
            },
            "weight_distribution": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "rationale": {"type": "string"},
                    "heavy_zones": {"type": "array", "items": {"type": "string"}},
                    "light_zones": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["pattern", "rationale", "heavy_zones", "light_zones"],
                "additionalProperties": False,
            },
            "breathing_room": {
                "type": "object",
                "properties": {
                    "breathing_m": {"type": "number"},
                    "quality": {"type": "string"},
                    "compared_to_threshold": {"type": "string"},
                },
                "required": ["breathing_m", "quality", "compared_to_threshold"],
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
            "space_summary",
            "positive_negative_analysis",
            "weight_distribution",
            "breathing_room",
            "watchouts",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: SolidVoidRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the solid_void_spec JSON. Anchor on computed_geometry (do not invent numbers). "
        "Pick exactly one weight_distribution.pattern and one breathing_room.quality from the catalogues."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    summary = (spec.get("space_summary") or "").strip()
    pna = spec.get("positive_negative_analysis") or {}
    wd = spec.get("weight_distribution") or {}
    br = spec.get("breathing_room") or {}
    wos = spec.get("watchouts") or []

    overlay_parts: list[str] = []

    # Top caption — space summary.
    if summary:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Space: " + _wrap(summary, 110), size=11, fill=INK))

    # Right rail — solid/void gauge + breathing + weight pattern.
    rail_w = 220
    rail_x = canvas_w - rail_w - 8
    rail_y = 130
    rail_h = max(220, 80 + 22 * (len(wos) + 4))
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))

    cursor_y = rail_y + 18
    overlay_parts.append(text(rail_x + 12, cursor_y, "Solid / void split", size=11, fill=INK, weight="600"))
    cursor_y += 16
    solid_pct = float(pna.get("solid_pct") or 0)
    void_pct = float(pna.get("void_pct") or 0)
    bar_x = rail_x + 12
    bar_w = rail_w - 24
    bar_h = 18
    # Two-segment bar.
    solid_w = max(0.0, min(100.0, solid_pct)) / 100.0 * bar_w
    overlay_parts.append(rect(bar_x, cursor_y, bar_w, bar_h, fill=PAPER_DEEP, stroke=INK_SOFT, stroke_width=0.5))
    overlay_parts.append(rect(bar_x, cursor_y, solid_w, bar_h, fill=INK, stroke="none"))
    overlay_parts.append(text(bar_x + 6, cursor_y + 13, f"solid {solid_pct:.0f}%", size=10, fill="white", weight="600"))
    overlay_parts.append(text(bar_x + bar_w - 6, cursor_y + 13, f"void {void_pct:.0f}%", size=10, fill=INK, weight="600", anchor="end"))
    cursor_y += bar_h + 10
    if pna.get("interpretation"):
        overlay_parts.append(text(bar_x, cursor_y, _wrap(pna["interpretation"], 30), size=9, fill=INK_SOFT))
        cursor_y += 18

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Weight distribution", size=11, fill=INK, weight="600"))
    cursor_y += 16
    pattern = wd.get("pattern") or "—"
    overlay_parts.append(rect(bar_x, cursor_y - 8, 8, 8, fill=ACCENT_WARM, stroke="none"))
    overlay_parts.append(text(bar_x + 14, cursor_y, _wrap(pattern, 30), size=10, fill=INK, weight="600"))
    cursor_y += 12
    if wd.get("rationale"):
        overlay_parts.append(text(bar_x + 14, cursor_y, _wrap(wd["rationale"], 32), size=9, fill=INK_SOFT))
        cursor_y += 16

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Breathing room", size=11, fill=INK, weight="600"))
    cursor_y += 16
    br_m = br.get("breathing_m")
    br_q = br.get("quality") or "—"
    overlay_parts.append(rect(bar_x, cursor_y - 8, 8, 8, fill=ACCENT_COOL, stroke="none"))
    overlay_parts.append(text(bar_x + 14, cursor_y, f"{br_m if br_m is not None else '?'} m — {br_q}", size=10, fill=INK, weight="600"))
    cursor_y += 12
    if br.get("compared_to_threshold"):
        overlay_parts.append(text(bar_x + 14, cursor_y, _wrap(br["compared_to_threshold"], 32), size=9, fill=INK_SOFT))
        cursor_y += 16

    if wos:
        cursor_y += 6
        overlay_parts.append(text(rail_x + 12, cursor_y, "Watch-outs", size=11, fill=INK, weight="600"))
        cursor_y += 14
        for w in wos[:4]:
            overlay_parts.append(rect(bar_x, cursor_y - 8, 8, 8, fill="#7a4632", stroke="none"))
            overlay_parts.append(text(bar_x + 14, cursor_y, _wrap(w.get("title") or "", 30), size=10, fill=INK, weight="600"))
            cursor_y += 12
            overlay_parts.append(text(bar_x + 14, cursor_y, _wrap(w.get("detail") or "", 32), size=9, fill=INK_SOFT))
            cursor_y += 14

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class SolidVoidError(RuntimeError):
    """Raised when the LLM solid/void stage cannot produce a grounded spec."""


async def generate_solid_void_diagram(req: SolidVoidRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise SolidVoidError(
            "OpenAI API key is not configured. The solid/void diagram requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_solid_void_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise SolidVoidError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SOLID_VOID_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": SOLID_VOID_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for solid/void diagram")
        raise SolidVoidError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SolidVoidError("LLM returned malformed JSON") from exc

    # Validation.
    pattern = (spec.get("weight_distribution") or {}).get("pattern")
    quality = (spec.get("breathing_room") or {}).get("quality")
    computed = knowledge.get("computed_geometry", {}) or {}
    spec_solid = (spec.get("positive_negative_analysis") or {}).get("solid_pct")
    spec_void = (spec.get("positive_negative_analysis") or {}).get("void_pct")
    matches_computed_solid = (
        spec_solid is not None
        and computed.get("solid_pct") is not None
        and abs(float(spec_solid) - float(computed["solid_pct"])) <= 1.5
    )
    matches_computed_void = (
        spec_void is not None
        and computed.get("void_pct") is not None
        and abs(float(spec_void) - float(computed["void_pct"])) <= 1.5
    )
    validation = {
        "weight_pattern_in_scope": pattern in WEIGHT_DISTRIBUTION_PATTERNS,
        "breathing_quality_in_scope": quality in BREATHING_QUALITY,
        "solid_pct_matches_computed": matches_computed_solid,
        "void_pct_matches_computed": matches_computed_void,
    }

    base = solid_void.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "solid_void",
        "name": "Solid vs Void",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "solid_void_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "watchout_count": len(spec.get("watchouts", [])),
        },
    }


def _stub_graph(req: SolidVoidRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
