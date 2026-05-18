"""LLM-driven Massing diagram (BRD Layer 2B #3).

Two panels — horizontal massing (top-down footprint) + vertical massing
(side section silhouette). Combines the deterministic geometry renderer
in ``app.services.diagrams.massing`` with an LLM interpretation that
names the silhouette, calls out vertical weight distribution, and reads
the space allocation across the four BRD height bands.

Pipeline contract:

    INPUT (theme + design graph)
      → INJECT  (computed meta from massing.py renderer + theme
                 proportions + BRD height bands + ergonomic intent)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic 2-panel SVG + LLM interpretation overlay)
      → OUTPUT  (massing_spec JSON + annotated SVG)

The BRD §2B requirements (#3):
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.knowledge import themes
from app.services.diagrams import massing
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
from app.services.themes import get_theme as _get_theme_db

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
# Sectional silhouettes per BRD §1C massing reads — describe how the
# overall mass reads against the room volume from the side.
SILHOUETTE_PATTERNS = (
    "low_slung",            # body sits well below mid-height; lounge / mid-century
    "balanced_horizon",     # body holds mid-height; modern / contemporary
    "vertical_emphasis",    # tall body, accentuates height; pedestal verticals
    "stepped_terrace",      # graduated heights, terrace-like profile
    "monolithic_block",     # near-uniform tall mass; minimal articulation
    "cantilever_play",      # voids beneath solids; floating accents
)

# Vertical weight distribution — which BRD height band carries the visual
# weight (see ``app/services/diagrams/massing.py`` for the bands).
VERTICAL_DISTRIBUTION_PATTERNS = (
    "base_heavy",
    "body_heavy",
    "upper_heavy",
    "overhead_heavy",
    "evenly_distributed",
    "split_band",
)

# Top-down density patterns (how the footprint clusters across the room).
HORIZONTAL_DENSITY_PATTERNS = (
    "perimeter",
    "centred",
    "diagonal_split",
    "scattered",
    "linear_band",
)

# BRD height-band labels mirror the renderer's space-allocation bar.
HEIGHT_BANDS = ("0-0.5m (base)", "0.5-1.2m (body)", "1.2-2.0m (upper)", "2.0m+ (overhead)")


# ── Request schema ──────────────────────────────────────────────────────────


class MassingDiagramRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1000, ge=400, le=2400)
    canvas_height: int = Field(default=520, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_massing_knowledge(
    req: MassingDiagramRequest,
    *,
    theme_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = theme_pack if theme_pack is not None else (themes.get(req.theme) or {})
    graph = req.design_graph or _stub_graph(req, pack=pack)

    # Run the deterministic renderer first so the LLM gets actual numbers
    # (room dims + object count) to anchor on.
    base = massing.generate(graph, canvas_w=req.canvas_width, canvas_h=req.canvas_height)
    base_meta = base.get("meta", {})

    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "proportions": pack.get("proportions", {}),
            "geometry_intent": (pack.get("proportions") or {}).get("geometry_intent"),
            "ergonomic_intent": pack.get("ergonomic_intent"),
            "signature_moves": pack.get("signature_moves", []),
        },
        "computed_geometry": base_meta,
        "height_bands_in_scope": list(HEIGHT_BANDS),
        "silhouette_patterns_in_scope": list(SILHOUETTE_PATTERNS),
        "vertical_distribution_patterns_in_scope": list(VERTICAL_DISTRIBUTION_PATTERNS),
        "horizontal_density_patterns_in_scope": list(HORIZONTAL_DENSITY_PATTERNS),
        "graph_summary": {
            "object_count": len(graph.get("objects", [])),
            "object_types": sorted(
                {(o.get("type") or "").lower() for o in graph.get("objects", []) if o.get("type")}
            ),
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


MASSING_SYSTEM_PROMPT = """You are an architectural designer writing the *massing* sheet — the page that reads the overall silhouette, where the visual weight sits, and how the design occupies the four BRD height bands.

Read the [KNOWLEDGE] block — computed geometry (room dimensions, object_count), theme proportions + ergonomic intent, BRD height bands, and the three bounded vocabularies (silhouette, vertical distribution, horizontal density). Produce a structured spec covering four things:

  1. Silhouette — pick one pattern from silhouette_patterns_in_scope and justify it against the theme's geometry_intent.
  2. Vertical weight distribution — pick one pattern from vertical_distribution_patterns_in_scope; cite which BRD height band carries the most mass.
  3. Horizontal density — pick one pattern from horizontal_density_patterns_in_scope; describe the footprint clustering on the plan.
  4. Space allocation — for each of the four BRD height bands, write a one-line read of what occupies it (or "(empty)").

Hard rules:
- Cite actual numbers from computed_geometry (room dims, object_count) — do not invent.
- silhouette.pattern MUST be one of silhouette_patterns_in_scope.
- vertical_distribution.pattern MUST be one of vertical_distribution_patterns_in_scope.
- horizontal_density.pattern MUST be one of horizontal_density_patterns_in_scope.
- space_allocation MUST contain exactly the four height_bands_in_scope keys.
- Studio voice — short, technical, decisive. No marketing prose."""


MASSING_SCHEMA: dict[str, Any] = {
    "name": "massing_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Two sentences: the overall massing read (silhouette + weight)."
            },
            "silhouette": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["pattern", "rationale"],
                "additionalProperties": False,
            },
            "vertical_distribution": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "dominant_band": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["pattern", "dominant_band", "rationale"],
                "additionalProperties": False,
            },
            "horizontal_density": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["pattern", "rationale"],
                "additionalProperties": False,
            },
            "space_allocation": {
                "type": "object",
                "properties": {
                    "0-0.5m (base)": {"type": "string"},
                    "0.5-1.2m (body)": {"type": "string"},
                    "1.2-2.0m (upper)": {"type": "string"},
                    "2.0m+ (overhead)": {"type": "string"},
                },
                "required": list(HEIGHT_BANDS),
                "additionalProperties": False,
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "summary",
            "silhouette",
            "vertical_distribution",
            "horizontal_density",
            "space_allocation",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: MassingDiagramRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the massing_spec JSON. Anchor on computed_geometry (do not invent numbers). "
        "Pick exactly one pattern per axis from the bounded vocabularies. "
        "Fill all four height_bands_in_scope keys in space_allocation."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    summary = (spec.get("summary") or "").strip()
    sil = spec.get("silhouette") or {}
    vd = spec.get("vertical_distribution") or {}
    hd = spec.get("horizontal_density") or {}
    alloc = spec.get("space_allocation") or {}

    overlay_parts: list[str] = []

    # Top caption — summary band, full width.
    if summary:
        overlay_parts.append(
            rect(40, 70, canvas_w - 80, 30, fill=PAPER_DEEP, stroke="none", opacity=0.65)
        )
        overlay_parts.append(text(52, 89, _wrap(summary, 130), size=11, fill=INK))

    # Right rail with axis reads.
    rail_w = 240
    rail_x = canvas_w - rail_w - 8
    rail_y = 110
    rail_h = max(260, 80 + 22 * (len(alloc) + 3))
    overlay_parts.append(
        rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92)
    )

    cursor_y = rail_y + 18
    overlay_parts.append(text(rail_x + 12, cursor_y, "Silhouette", size=11, fill=INK, weight="600"))
    cursor_y += 16
    overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_WARM, stroke="none"))
    overlay_parts.append(
        text(rail_x + 26, cursor_y, _wrap(sil.get("pattern") or "—", 28), size=10, fill=INK, weight="600")
    )
    cursor_y += 12
    if sil.get("rationale"):
        overlay_parts.append(
            text(rail_x + 26, cursor_y, _wrap(sil["rationale"], 30), size=9, fill=INK_SOFT)
        )
        cursor_y += 16

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Vertical weight", size=11, fill=INK, weight="600"))
    cursor_y += 16
    overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_COOL, stroke="none"))
    overlay_parts.append(
        text(
            rail_x + 26,
            cursor_y,
            _wrap(f"{vd.get('pattern') or '—'} · {vd.get('dominant_band') or '—'}", 30),
            size=10,
            fill=INK,
            weight="600",
        )
    )
    cursor_y += 12
    if vd.get("rationale"):
        overlay_parts.append(
            text(rail_x + 26, cursor_y, _wrap(vd["rationale"], 30), size=9, fill=INK_SOFT)
        )
        cursor_y += 16

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Horizontal density", size=11, fill=INK, weight="600"))
    cursor_y += 16
    overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill="#7a4632", stroke="none"))
    overlay_parts.append(
        text(rail_x + 26, cursor_y, _wrap(hd.get("pattern") or "—", 28), size=10, fill=INK, weight="600")
    )
    cursor_y += 12
    if hd.get("rationale"):
        overlay_parts.append(
            text(rail_x + 26, cursor_y, _wrap(hd["rationale"], 30), size=9, fill=INK_SOFT)
        )
        cursor_y += 16

    cursor_y += 6
    overlay_parts.append(text(rail_x + 12, cursor_y, "Space allocation", size=11, fill=INK, weight="600"))
    cursor_y += 14
    for band in HEIGHT_BANDS:
        line_text = alloc.get(band) or "(empty)"
        overlay_parts.append(
            text(rail_x + 12, cursor_y, band, size=9, fill=INK_MUTED, weight="600")
        )
        cursor_y += 11
        overlay_parts.append(
            text(rail_x + 12, cursor_y, _wrap(line_text, 32), size=9, fill=INK_SOFT)
        )
        cursor_y += 14

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class MassingDiagramError(RuntimeError):
    """Raised when the LLM massing stage cannot produce a grounded spec."""


async def generate_massing_diagram(
    req: MassingDiagramRequest,
    *,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise MassingDiagramError(
            "OpenAI API key is not configured. The massing diagram requires "
            "a live LLM call; no static fallback is served."
        )

    if session is not None:
        theme_pack = await _get_theme_db(session, req.theme)
    else:
        from app.database import async_session_factory  # local import

        async with async_session_factory() as own_session:
            theme_pack = await _get_theme_db(own_session, req.theme)

    knowledge = build_massing_knowledge(req, theme_pack=theme_pack)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise MassingDiagramError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": MASSING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": MASSING_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for massing diagram")
        raise MassingDiagramError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MassingDiagramError("LLM returned malformed JSON") from exc

    silhouette_pattern = (spec.get("silhouette") or {}).get("pattern")
    vd_pattern = (spec.get("vertical_distribution") or {}).get("pattern")
    hd_pattern = (spec.get("horizontal_density") or {}).get("pattern")
    alloc_keys = set((spec.get("space_allocation") or {}).keys())
    validation = {
        "silhouette_pattern_in_scope": silhouette_pattern in SILHOUETTE_PATTERNS,
        "vertical_distribution_pattern_in_scope": vd_pattern in VERTICAL_DISTRIBUTION_PATTERNS,
        "horizontal_density_pattern_in_scope": hd_pattern in HORIZONTAL_DENSITY_PATTERNS,
        "all_height_bands_filled": alloc_keys == set(HEIGHT_BANDS),
    }

    base = massing.generate(
        req.design_graph or _stub_graph(req, pack=theme_pack),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "massing",
        "name": "Massing",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "massing_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
        },
    }


def _stub_graph(
    req: MassingDiagramRequest,
    *,
    pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 6000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 5000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 3000) / 1000.0)
    style_pack = pack if pack is not None else (themes.get(req.theme) or {})
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": style_pack.get("display_name") or req.theme},
        "objects": [],
    }
