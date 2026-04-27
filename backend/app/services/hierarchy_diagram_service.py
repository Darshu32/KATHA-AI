"""LLM-driven Hierarchy diagram (BRD Layer 2B #8).

Three stacked rankings — visual, material, functional — that explain
which moves dominate, which support, which decorate. Same pipeline
contract as the other 2B services:

    INPUT (theme + design graph + parametric_spec)
      → INJECT  (theme palette + signature moves +
                 functional-bucket taxonomy + emphasis-tier vocabulary +
                 graph object/material summary)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic three-rank base + LLM tier annotations)
      → OUTPUT  (hierarchy_spec JSON + annotated SVG)

The four BRD requirements:
  • Visual hierarchy (dominant, secondary, accent)
  • Material hierarchy (primary, secondary, detail)
  • Functional hierarchy (primary purpose, secondary, storage)
  • Generated from design rules + emphasis settings
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
from app.services.diagrams import hierarchy
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
VISUAL_TIERS = ("dominant", "secondary", "accent")
MATERIAL_TIERS = ("primary", "secondary", "detail")
FUNCTIONAL_TIERS = ("primary_purpose", "secondary_use", "storage", "accent")


# ── Request schema ──────────────────────────────────────────────────────────


class HierarchyRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _summarise_graph(graph: dict[str, Any]) -> dict[str, Any]:
    objs = graph.get("objects", [])
    types = sorted({(o.get("type") or "").lower() for o in objs if o.get("type")})
    materials = sorted({(m.get("name") or "").lower() for m in graph.get("materials", []) if m.get("name")})
    return {
        "object_count": len(objs),
        "object_types": types,
        "materials_in_use": materials,
        "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
    }


def build_hierarchy_knowledge(req: HierarchyRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    palette = pack.get("material_palette", {})
    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "material_palette": palette,
            "colour_palette": pack.get("colour_palette", []),
            "colour_strategy": pack.get("colour_strategy"),
            "signature_moves": pack.get("signature_moves", []),
            "ergonomic_intent": pack.get("ergonomic_intent"),
        },
        "visual_tiers_in_scope": list(VISUAL_TIERS),
        "material_tiers_in_scope": list(MATERIAL_TIERS),
        "functional_tiers_in_scope": list(FUNCTIONAL_TIERS),
        "functional_buckets": dict(hierarchy.FUNCTIONAL_BUCKETS),
        "graph_summary": _summarise_graph(req.design_graph or {}),
        "parametric_summary": {
            "primary_species": (req.parametric_spec or {}).get("wood_spec", {}).get("primary_species"),
            "secondary_species": (req.parametric_spec or {}).get("wood_spec", {}).get("secondary_species"),
            "hardware_material": (req.parametric_spec or {}).get("hardware_spec", {}).get("material"),
        },
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


HIERARCHY_AUTHOR_SYSTEM_PROMPT = """You are an architectural designer writing the *hierarchy* sheet — the page that ranks every visible move in the project so a reader knows what dominates, what supports, and what decorates.

Read the [KNOWLEDGE] block and produce three independent rankings:

  1. Visual hierarchy       — assign each anchor object a tier from visual_tiers_in_scope (dominant / secondary / accent).
  2. Material hierarchy     — rank materials in use by tier from material_tiers_in_scope (primary / secondary / detail).
  3. Functional hierarchy   — sort object types into functional_tiers_in_scope (primary_purpose / secondary_use / storage / accent), respecting the functional_buckets taxonomy.

Hard rules:
- visual_tier MUST be in visual_tiers_in_scope.
- material_tier MUST be in material_tiers_in_scope.
- functional_tier MUST be in functional_tiers_in_scope.
- Reference real object types from graph_summary.object_types and real materials from graph_summary.materials_in_use OR theme.material_palette / parametric_summary.
- Each tier assignment carries a one-line emphasis_rule that explains why.
- If a tier is genuinely empty, omit it — do not pad.
- Studio voice — short, technical, decisive."""


HIERARCHY_SCHEMA: dict[str, Any] = {
    "name": "hierarchy_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "hierarchy_summary": {
                "type": "string",
                "description": "Two sentences: the over-arching ranking the design reads as.",
            },
            "visual_hierarchy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object": {"type": "string"},
                        "tier": {"type": "string"},
                        "emphasis_rule": {"type": "string"},
                    },
                    "required": ["object", "tier", "emphasis_rule"],
                    "additionalProperties": False,
                },
            },
            "material_hierarchy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "material": {"type": "string"},
                        "tier": {"type": "string"},
                        "emphasis_rule": {"type": "string"},
                    },
                    "required": ["material", "tier", "emphasis_rule"],
                    "additionalProperties": False,
                },
            },
            "functional_hierarchy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "tier": {"type": "string"},
                        "emphasis_rule": {"type": "string"},
                    },
                    "required": ["object_type", "tier", "emphasis_rule"],
                    "additionalProperties": False,
                },
            },
            "rules_invoked": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "hierarchy_summary",
            "visual_hierarchy",
            "material_hierarchy",
            "functional_hierarchy",
            "rules_invoked",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: HierarchyRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the hierarchy_spec JSON. Cover every meaningful object and material. "
        "Use only known tiers. Each entry carries one emphasis_rule line."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _tier_colour(tier: str, vocabulary: tuple[str, ...]) -> str:
    """Map tier to ink intensity — top tier = ink, mid = soft, low = muted."""
    try:
        idx = vocabulary.index(tier)
    except ValueError:
        return INK_MUTED
    return [INK, ACCENT_WARM, ACCENT_COOL, INK_MUTED][min(idx, 3)]


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    summary = (spec.get("hierarchy_summary") or "").strip()
    visual = spec.get("visual_hierarchy") or []
    material = spec.get("material_hierarchy") or []
    functional = spec.get("functional_hierarchy") or []
    rules = spec.get("rules_invoked") or []

    overlay_parts: list[str] = []

    # Top caption — overall ranking.
    if summary:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Hierarchy: " + _wrap(summary, 110), size=11, fill=INK))

    # Three columns side-by-side: visual, material, functional.
    col_y = 130
    col_h = canvas_h - 200
    col_w = (canvas_w - 80 - 24) // 3
    col_gap = 12
    col_x_visual = 40
    col_x_material = col_x_visual + col_w + col_gap
    col_x_functional = col_x_material + col_w + col_gap

    def _render_column(x: float, title: str, rows: list[dict], vocabulary: tuple[str, ...], item_key: str) -> None:
        overlay_parts.append(rect(x, col_y, col_w, col_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))
        overlay_parts.append(text(x + 12, col_y + 18, title, size=11, fill=INK, weight="600"))
        cy = col_y + 38
        for tier in vocabulary:
            tier_rows = [r for r in rows if (r.get("tier") or "").lower() == tier]
            if not tier_rows:
                continue
            colour = _tier_colour(tier, vocabulary)
            overlay_parts.append(rect(x + 12, cy - 8, 8, 8, fill=colour, stroke="none"))
            overlay_parts.append(text(x + 26, cy, tier.replace("_", " ").upper(), size=10, fill=INK, weight="600"))
            cy += 14
            for row in tier_rows[:5]:
                label = row.get(item_key) or ""
                rule = row.get("emphasis_rule") or ""
                overlay_parts.append(text(x + 26, cy, _wrap(label, 24), size=10, fill=INK))
                cy += 12
                if rule:
                    overlay_parts.append(text(x + 26, cy, _wrap(rule, 28), size=9, fill=INK_SOFT))
                    cy += 12
            cy += 6

    _render_column(col_x_visual, "Visual", visual, VISUAL_TIERS, "object")
    _render_column(col_x_material, "Material", material, MATERIAL_TIERS, "material")
    _render_column(col_x_functional, "Functional", functional, FUNCTIONAL_TIERS, "object_type")

    # Footer — rules invoked.
    if rules:
        overlay_parts.append(text(40, canvas_h - 14, "Rules invoked: " + _wrap(", ".join(rules), 130), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class HierarchyError(RuntimeError):
    """Raised when the LLM hierarchy stage cannot produce a grounded spec."""


async def generate_hierarchy_diagram(req: HierarchyRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise HierarchyError(
            "OpenAI API key is not configured. The hierarchy stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_hierarchy_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HierarchyError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": HIERARCHY_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": HIERARCHY_SCHEMA,
            },
            temperature=0.4,
            max_tokens=1800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for hierarchy diagram")
        raise HierarchyError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HierarchyError("LLM returned malformed JSON") from exc

    bad_visual = [r.get("tier") for r in (spec.get("visual_hierarchy") or []) if r.get("tier") not in VISUAL_TIERS]
    bad_material = [r.get("tier") for r in (spec.get("material_hierarchy") or []) if r.get("tier") not in MATERIAL_TIERS]
    bad_functional = [r.get("tier") for r in (spec.get("functional_hierarchy") or []) if r.get("tier") not in FUNCTIONAL_TIERS]
    validation = {
        "visual_tiers_valid": not bad_visual,
        "bad_visual_tiers": bad_visual,
        "material_tiers_valid": not bad_material,
        "bad_material_tiers": bad_material,
        "functional_tiers_valid": not bad_functional,
        "bad_functional_tiers": bad_functional,
    }

    base = hierarchy.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, req.canvas_height)

    return {
        "id": "hierarchy",
        "name": "Hierarchy",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "hierarchy_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "visual_count": len(spec.get("visual_hierarchy", [])),
            "material_count": len(spec.get("material_hierarchy", [])),
            "functional_count": len(spec.get("functional_hierarchy", [])),
        },
    }


def _stub_graph(req: HierarchyRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
        "materials": [],
    }
