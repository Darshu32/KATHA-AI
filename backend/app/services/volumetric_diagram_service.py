"""LLM-driven Volumetric Hierarchy diagram (BRD Layer 2B #3).

Vertical × Horizontal reading of the design — the architect's section +
plan-share view in one drawing. Same pipeline contract as the other
2B services:

    INPUT (parametric spec or design graph + theme)
      → INJECT  (theme proportions + ergonomic intent + zone taxonomy
                 + stacking-logic catalogue + parametric geometry)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic axonometric base + LLM annotations)
      → OUTPUT  (volumetric_hierarchy_spec JSON  +  annotated SVG)

The four BRD requirements:
  • Overall silhouette in section
  • Weight distribution visual
  • Space allocation breakdown
  • Generated from dimensions + stacking logic
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
from app.services.diagrams import hierarchy, volumetric
from app.services.diagrams.svg_base import (
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


# ── Stacking logic catalogue ───────────────────────────────────────────────
# The vocabulary the LLM picks from — keeps the output bounded so the
# renderer can react to known keys without hardcoding an answer.
STACKING_LOGICS = {
    "grounded_heavy_base": "Heaviest mass at floor (plinth, low cabinet); piece tapers upward.",
    "floating_body_on_plinth": "Distinct base + lighter body above; shadow-gap reveal.",
    "balanced_horizontal": "Mass distributed evenly across the horizontal plane; low-slung.",
    "vertical_stack": "Stacked equal modules — repetition reads as the form.",
    "cantilever_overhang": "Base offset from the body above — visual tension at the joint.",
    "asymmetric_balance": "One side weighted; visual counterweight from a smaller mass opposite.",
}

WEIGHT_BANDS = ("low", "mid", "high")


# ── Request schema ──────────────────────────────────────────────────────────


class VolumetricDiagramRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_volumetric_knowledge(req: VolumetricDiagramRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    graph = req.design_graph or {}
    objects = graph.get("objects", [])
    obj_summary = []
    for o in objects[:30]:
        d = o.get("dimensions") or {}
        obj_summary.append({
            "type": (o.get("type") or "").lower(),
            "length_mm": d.get("length"),
            "width_mm": d.get("width"),
            "height_mm": d.get("height"),
        })

    geom = (req.parametric_spec or {}).get("geometry") or {}

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
            "material_pattern": pack.get("material_pattern", {}),
        },
        "stacking_logics_in_scope": STACKING_LOGICS,
        "weight_bands": WEIGHT_BANDS,
        "functional_buckets": dict(hierarchy.FUNCTIONAL_BUCKETS),
        "graph_summary": {
            "object_count": len(objects),
            "objects": obj_summary,
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
        "parametric_geometry": geom,
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


VOLUMETRIC_AUTHOR_SYSTEM_PROMPT = """You are an architectural designer writing the *volumetric hierarchy* sheet of a project — the page that explains how the form sits in space, where the weight is, and how the volume is shared between functions.

Read the [KNOWLEDGE] block and produce a structured spec covering four things:
  1. Overall silhouette in section — a one-line read of the vertical profile.
  2. Weight distribution — where the visual weight sits (low / mid / high) and why.
  3. Space allocation — percentage share of the volume across functional buckets that sum to 100.
  4. Stacking logic — pick one key from stacking_logics_in_scope and justify it from the theme.

Hard rules:
- The stacking_logic key MUST be a key in stacking_logics_in_scope.
- Each space_allocation bucket MUST be a key in functional_buckets.
- weight_band MUST be one of weight_bands.
- Cite a real signature_move from theme.signature_moves where applicable.
- Quantify everything you can — heights in mm, percentages, ratios.
- If a field is missing, name the assumption explicitly.
- Studio voice — short, technical, decisive."""


VOLUMETRIC_DIAGRAM_SCHEMA: dict[str, Any] = {
    "name": "volumetric_hierarchy_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "silhouette_section": {
                "type": "string",
                "description": "One sentence: the vertical profile of the piece / room from low to high.",
            },
            "weight_distribution": {
                "type": "object",
                "properties": {
                    "weight_band": {"type": "string"},
                    "percent_at_floor": {"type": "number"},
                    "percent_at_mid": {"type": "number"},
                    "percent_at_top": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["weight_band", "percent_at_floor", "percent_at_mid", "percent_at_top", "rationale"],
                "additionalProperties": False,
            },
            "space_allocation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bucket": {"type": "string"},
                        "percent": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["bucket", "percent", "note"],
                    "additionalProperties": False,
                },
            },
            "stacking_logic": {
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
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "silhouette_section",
            "weight_distribution",
            "space_allocation",
            "stacking_logic",
            "signature_moves_in_play",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: VolumetricDiagramRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the volumetric_hierarchy_spec JSON. Pick one stacking logic. "
        "Make space_allocation percentages sum to 100. Use only known buckets and known stacking keys."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    """Add silhouette caption, weight-distribution gauge, and space-allocation bar."""
    wd = spec.get("weight_distribution") or {}
    sa = spec.get("space_allocation") or []
    stack = spec.get("stacking_logic") or {}
    sig = spec.get("signature_moves_in_play") or []

    overlay_parts: list[str] = []

    # Top caption — silhouette in section.
    sil = (spec.get("silhouette_section") or "").strip()
    if sil:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Silhouette: " + _wrap(sil, 110), size=11, fill=INK))

    # Right rail: weight distribution gauge (3 stacked bars).
    rail_w = 220
    rail_x = canvas_w - rail_w - 8
    rail_y = 130
    rail_h = 230
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))
    overlay_parts.append(text(rail_x + 12, rail_y + 18, "Weight distribution", size=11, fill=INK, weight="600"))

    band = (wd.get("weight_band") or "").lower()
    pct_top = float(wd.get("percent_at_top") or 0)
    pct_mid = float(wd.get("percent_at_mid") or 0)
    pct_floor = float(wd.get("percent_at_floor") or 0)

    bar_x = rail_x + 12
    bar_w = 80
    bar_h = 18
    bar_y = rail_y + 36
    for label, pct, hl in (
        ("Top", pct_top, band == "high"),
        ("Mid", pct_mid, band == "mid"),
        ("Floor", pct_floor, band == "low"),
    ):
        fill = ACCENT_WARM if hl else INK_SOFT
        # Background track.
        overlay_parts.append(rect(bar_x + 50, bar_y, bar_w, bar_h, fill=PAPER_DEEP, stroke="none"))
        # Filled portion.
        filled = max(0.0, min(100.0, pct)) / 100.0 * bar_w
        overlay_parts.append(rect(bar_x + 50, bar_y, filled, bar_h, fill=fill, stroke="none"))
        overlay_parts.append(text(bar_x, bar_y + 13, label, size=10, fill=INK))
        overlay_parts.append(text(bar_x + 52 + bar_w + 6, bar_y + 13, f"{pct:.0f}%", size=10, fill=INK_SOFT))
        bar_y += bar_h + 8

    if wd.get("rationale"):
        overlay_parts.append(text(rail_x + 12, bar_y + 14, _wrap(wd["rationale"], 30), size=9, fill=INK_SOFT))

    # Space allocation horizontal bar — across the bottom.
    if sa:
        sa_y = canvas_h - 80
        sa_x = 40
        sa_w = canvas_w - 80 - rail_w - 24
        overlay_parts.append(text(sa_x, sa_y - 6, "Space allocation", size=11, fill=INK, weight="600"))
        overlay_parts.append(rect(sa_x, sa_y, sa_w, 22, fill=PAPER_DEEP, stroke=INK_SOFT, stroke_width=0.5))
        cursor = sa_x
        total = sum(max(0.0, float(b.get("percent") or 0)) for b in sa) or 100.0
        palette = [INK, INK_SOFT, INK_MUTED, ACCENT_WARM, "#7a4632", "#3a5a4a"]
        for i, b in enumerate(sa[:6]):
            pct = max(0.0, float(b.get("percent") or 0)) / total
            seg_w = pct * sa_w
            overlay_parts.append(rect(cursor, sa_y, seg_w, 22, fill=palette[i % len(palette)], stroke="none", opacity=0.85))
            if seg_w > 36:
                overlay_parts.append(text(cursor + 6, sa_y + 15, f"{b.get('bucket')} {b.get('percent'):.0f}%", size=9, fill="white", weight="600"))
            cursor += seg_w
        # Notes line.
        notes = " • ".join(f"{b.get('bucket')}: {b.get('note')}" for b in sa[:3] if b.get("note"))
        if notes:
            overlay_parts.append(text(sa_x, sa_y + 38, _wrap(notes, 100), size=9, fill=INK_SOFT))

    # Footer — stacking logic + signature.
    footer_bits: list[str] = []
    if stack.get("display_name"):
        footer_bits.append(f"Stacking: {stack['display_name']}")
    if stack.get("rationale"):
        footer_bits.append(stack["rationale"])
    if sig:
        footer_bits.append("Signature: " + "; ".join(sig[:2]))
    if footer_bits:
        overlay_parts.append(text(40, canvas_h - 14, _wrap(" • ".join(footer_bits), 140), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class VolumetricDiagramError(RuntimeError):
    """Raised when the volumetric LLM stage cannot produce a grounded spec."""


async def generate_volumetric_diagram(req: VolumetricDiagramRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise VolumetricDiagramError(
            "OpenAI API key is not configured. The volumetric-hierarchy stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_volumetric_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise VolumetricDiagramError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": VOLUMETRIC_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": VOLUMETRIC_DIAGRAM_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for volumetric diagram")
        raise VolumetricDiagramError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VolumetricDiagramError("LLM returned malformed JSON") from exc

    # Validation.
    stack_key = (spec.get("stacking_logic") or {}).get("key")
    weight_band = (spec.get("weight_distribution") or {}).get("weight_band", "").lower()
    sa = spec.get("space_allocation") or []
    valid_buckets = set(hierarchy.FUNCTIONAL_BUCKETS.keys())
    bad_buckets = [b.get("bucket") for b in sa if b.get("bucket") not in valid_buckets]
    sa_total = sum(max(0.0, float(b.get("percent") or 0)) for b in sa)

    validation = {
        "stacking_in_catalogue": stack_key in STACKING_LOGICS,
        "weight_band_valid": weight_band in WEIGHT_BANDS,
        "buckets_in_taxonomy": not bad_buckets,
        "bad_buckets": bad_buckets,
        "space_allocation_total_percent": round(sa_total, 1),
        "space_allocation_sums_to_100": abs(sa_total - 100.0) <= 1.5,
    }

    base = volumetric.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "volumetric_hierarchy",
        "name": "Volumetric Hierarchy",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "volumetric_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "stacking_key": stack_key,
            "weight_band": weight_band,
            "bucket_count": len(sa),
        },
    }


def _stub_graph(req: VolumetricDiagramRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
    }
