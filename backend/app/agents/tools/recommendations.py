"""Stage 10 agent tools — proactive recommendations (BRD §6).

BRD §6 asks for the platform to surface forward-looking, actionable
tips on top of the validators ("validator says wrong; recommendations
say what to do better, and why").

Two tools ship to give the agent both speeds:

- :func:`quick_recommendations` — pure-Python, deterministic,
  millisecond-fast. Uses :mod:`app.services.recommendations` over a
  design graph: theme/material pairing, cost flags, lead-time band
  notes, volume pricing tips, sustainability nudges. Use this on
  every design-graph edit / generation as an "always-on" pass.
- :func:`full_recommendations` — LLM-driven, BRD §6 advisor. Uses
  :mod:`app.services.recommendations_service` to author a categorised
  list with confidence / impact / effort labels and citations from
  the knowledge base. Use when the user asks for advice or after
  major decisions.

Why two tools instead of one
----------------------------
The deterministic engine fires on every cycle without user prompting
(safe to call proactively — no LLM cost). The LLM advisor is the
"give me the studio's full opinion" mode and is heavier (~one
OpenAI call per invocation) so it stays opt-in / on-demand.

Proactive behaviour
-------------------
"Proactive" is a *system-prompt* concern, not a tool concern. The
agent system prompt should say: *"After every estimate, generation,
or material change, call quick_recommendations and surface any
results to the user."* The tool just makes sure the capability
exists; the agent decides when to fire it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.recommendations import recommend as quick_recommend
from app.services.recommendations_service import (
    RecommendationsRequest,
    generate_recommendations,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 1. quick_recommendations — fast, deterministic, no LLM
# ─────────────────────────────────────────────────────────────────────


class QuickRecommendationsInput(BaseModel):
    design_graph: dict[str, Any] = Field(
        description=(
            "A design graph dict — same shape the design pipeline "
            "produces. Must include `style.primary` (theme key) and "
            "`materials` (list of {name, category}) for the engine "
            "to fire all five recommenders."
        ),
    )


class RecommendationItem(BaseModel):
    id: str
    category: str
    """One of materials | cost | lead_time | theme | volume |
    sustainability."""
    severity: str
    """One of info | tip | nudge."""
    title: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class QuickRecommendationsOutput(BaseModel):
    count: int
    recommendations: list[RecommendationItem] = Field(default_factory=list)


@tool(
    name="quick_recommendations",
    description=(
        "Run the deterministic Python recommendations engine over a "
        "design graph (BRD §6). Fires across five recommenders: "
        "theme-material pairing, material-cost alternatives, "
        "manufacturing lead-time bands, volume-pricing tips, and "
        "sustainability nudges. No LLM call — millisecond latency. "
        "Read-only. Call proactively after every estimate, "
        "generation, or material change to surface forward-looking "
        "tips before the user asks."
    ),
    timeout_seconds=10.0,
)
async def quick_recommendations(
    ctx: ToolContext,
    input: QuickRecommendationsInput,
) -> QuickRecommendationsOutput:
    try:
        recs = quick_recommend(dict(input.design_graph or {}))
    except Exception as exc:  # noqa: BLE001 — defensive
        raise ToolError(
            f"Recommendations engine failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    items: list[RecommendationItem] = []
    for r in recs:
        try:
            items.append(RecommendationItem(
                id=str(r.get("id") or ""),
                category=str(r.get("category") or "general"),
                severity=str(r.get("severity") or "info"),
                title=str(r.get("title") or ""),
                message=str(r.get("message") or ""),
                evidence=dict(r.get("evidence") or {}),
            ))
        except Exception:  # noqa: BLE001 — skip bad rows
            logger.warning("recommendations.bad_row", extra={"row": r})

    return QuickRecommendationsOutput(
        count=len(items),
        recommendations=items,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. full_recommendations — LLM-driven BRD §6 advisor
# ─────────────────────────────────────────────────────────────────────


class FullRecommendationsInput(BaseModel):
    project_name: str = Field(
        default="KATHA Project",
        max_length=200,
    )
    theme: str = Field(
        default="",
        max_length=64,
        description=(
            "Theme key — e.g. 'pedestal', 'mid_century_modern'. The "
            "advisor uses this to fire the theme-material-pairing "
            "recommender."
        ),
    )
    piece_type: str = Field(
        default="",
        max_length=80,
        description="e.g. 'lounge_chair', 'dining_table'.",
    )
    primary_material: str = Field(
        default="",
        max_length=80,
        description="e.g. 'walnut'. Drives material-alternative tips.",
    )
    primary_material_family: str = Field(
        default="",
        max_length=32,
        description=(
            "Family — e.g. 'wood', 'metal', 'fabric'. Looks up "
            "alternatives within the same family."
        ),
    )
    dimensions_m: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Piece dimensions in metres — {width, depth, height, "
            "seat_height?}. Used for the ergonomic-band recommender."
        ),
    )
    complexity: str = Field(
        default="moderate",
        max_length=32,
        description=(
            "Manufacturing complexity — simple / moderate / complex. "
            "Drives the lead-time recommender."
        ),
    )
    units: int = Field(
        default=1,
        ge=1,
        le=10000,
        description="Volume — drives the volume-economies recommender.",
    )
    city: str = Field(
        default="",
        max_length=80,
        description="City — drives the supplier/region price-index tips.",
    )
    budget_inr: Optional[float] = Field(
        default=None,
        ge=0,
        description="Budget in INR — the advisor flags overruns.",
    )
    notes: str = Field(
        default="",
        max_length=600,
        description="Free-form context for the advisor LLM call.",
    )


class FullRecommendationsOutput(BaseModel):
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Slim block — count + top categories — for the agent to "
            "narrate before showing the full list."
        ),
    )
    recommendations: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Full BRD §6 advisor output — categorised list with "
            "confidence / impact / effort labels, evidence, and "
            "citations from the knowledge base. JSON-safe."
        ),
    )


@tool(
    name="full_recommendations",
    description=(
        "Run the LLM-driven BRD §6 recommendations advisor. Authors "
        "a categorised list of forward-looking tips across "
        "theme-material pairing, dimension alternatives, material "
        "alternatives, manufacturing lead-time, volume economies, "
        "compliance alerts, and supplier/region notes. Each item "
        "has confidence / impact / effort labels and cites the "
        "knowledge base (theme rule packs, material catalogue, BRD "
        "lead-time bands, volume tiers, regional price index). "
        "Heavier than quick_recommendations — one OpenAI call per "
        "invocation. Use when the user explicitly asks for advice "
        "or after major project decisions. Read-only."
    ),
    timeout_seconds=90.0,
)
async def full_recommendations(
    ctx: ToolContext,
    input: FullRecommendationsInput,
) -> FullRecommendationsOutput:
    try:
        req = RecommendationsRequest(
            project_name=input.project_name,
            theme=input.theme,
            piece_type=input.piece_type,
            primary_material=input.primary_material,
            primary_material_family=input.primary_material_family,
            dimensions_m=dict(input.dimensions_m or {}),
            complexity=input.complexity,
            units=int(input.units),
            city=input.city,
            budget_inr=input.budget_inr,
            notes=input.notes,
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Invalid request: {exc}") from exc

    try:
        result = await generate_recommendations(req)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            f"Recommendations advisor failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    recs_block = result.get("recommendations") or {}
    items = list(recs_block.get("items") or [])
    by_category: dict[str, int] = {}
    for it in items:
        cat = str((it or {}).get("category") or "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    summary = {
        "count": len(items),
        "top_categories": sorted(
            by_category.items(), key=lambda kv: -kv[1],
        )[:5],
        "theme": input.theme,
        "piece_type": input.piece_type,
    }

    return FullRecommendationsOutput(
        summary=summary,
        recommendations=recs_block,
    )
