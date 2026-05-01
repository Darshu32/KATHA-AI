"""Stage 7 — multi-modal agent tools.

The agent's vision surface. One foundational tool plus four
sugar-wrapped specialisations:

- :func:`analyze_image` — generic; takes a ``purpose`` slug.
- :func:`analyze_site_photo` — wraps purpose=``site_photo``.
- :func:`extract_aesthetic` — wraps purpose=``mood_board`` /
  ``reference`` for 1-N images.
- :func:`sketch_to_floor_plan` — wraps purpose=``hand_sketch``.
- :func:`digitize_floor_plan` — wraps purpose=``existing_floor_plan``.

All five are **read-only** (they read uploads + call vision; nothing
mutates DB state). They're eligible for the Stage-5 parallel
dispatcher.

Owner-scoped — every tool requires ``ctx.actor_id`` and refuses to
analyse uploads owned by anyone else (the analyzer enforces this
at the DB layer).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.vision import VisionAnalyzeError, VisionAnalyzer
from app.vision.prompts import SUPPORTED_PURPOSES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared output shapes
# ─────────────────────────────────────────────────────────────────────


class AssetRef(BaseModel):
    """One asset that participated in this analysis."""

    asset_id: str
    kind: str
    mime_type: str
    size_bytes: int
    label: str = ""


class VisionAnalysisOutput(BaseModel):
    """Generic shape every vision tool returns."""

    purpose: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    assets: list[AssetRef] = Field(default_factory=list)
    parsed: dict[str, Any] = Field(
        description=(
            "Structured result matching the purpose-specific schema. "
            "See docs/agents/multimodal.md for the per-purpose shape."
        ),
    )


def _require_actor(ctx: ToolContext) -> str:
    if not ctx.actor_id:
        raise ToolError(
            "No actor_id on the agent context. Vision tools require "
            "an authenticated user — uploads are owner-scoped."
        )
    return ctx.actor_id


def _wrap(outcome) -> VisionAnalysisOutput:
    """Adapt an :class:`AnalyzeOutcome` into the public output."""
    return VisionAnalysisOutput(
        purpose=outcome.purpose,
        provider=outcome.provider,
        model=outcome.model,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        assets=[
            AssetRef(
                asset_id=a.asset_id,
                kind=a.kind,
                mime_type=a.mime_type,
                size_bytes=a.size_bytes,
                label=a.label,
            )
            for a in outcome.assets
        ],
        parsed=outcome.parsed,
    )


async def _run_analyzer(
    ctx: ToolContext,
    *,
    asset_ids: list[str],
    purpose: str,
    focus: str = "",
    max_tokens: int = 1500,
) -> VisionAnalysisOutput:
    actor_id = _require_actor(ctx)
    analyzer = VisionAnalyzer()
    try:
        outcome = await analyzer.analyze_assets(
            ctx.session,
            owner_id=actor_id,
            asset_ids=asset_ids,
            purpose=purpose,
            focus=focus,
            max_tokens=max_tokens,
        )
    except VisionAnalyzeError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap(outcome)


# ─────────────────────────────────────────────────────────────────────
# 1. analyze_image (foundational)
# ─────────────────────────────────────────────────────────────────────


class AnalyzeImageInput(BaseModel):
    asset_id: str = Field(
        description=(
            "Id of the uploaded asset (from POST /v2/uploads). The "
            "asset must belong to the calling user."
        ),
        min_length=1,
        max_length=120,
    )
    purpose: str = Field(
        description=(
            "What kind of analysis to run. One of: 'site_photo', "
            "'reference', 'mood_board', 'hand_sketch', "
            "'existing_floor_plan'. The purpose drives the system "
            "prompt + output schema."
        ),
        max_length=64,
    )
    focus: str = Field(
        default="",
        max_length=500,
        description=(
            "Optional focus areas — 'pay attention to the kitchen "
            "island geometry', 'extract just the colour palette'. "
            "Folded into the user message verbatim."
        ),
    )


@tool(
    name="analyze_image",
    description=(
        "Run a vision analysis on an uploaded image with a specific "
        "purpose (site survey, aesthetic extraction, mood-board "
        "synthesis, sketch-to-DesignGraph, floor-plan digitisation). "
        "The output schema depends on the purpose — see "
        "docs/agents/multimodal.md. Owner-scoped: only the user's "
        "own uploads are accepted. Read-only."
    ),
    timeout_seconds=90.0,
)
async def analyze_image(
    ctx: ToolContext,
    input: AnalyzeImageInput,
) -> VisionAnalysisOutput:
    if input.purpose not in SUPPORTED_PURPOSES:
        raise ToolError(
            f"Unknown purpose {input.purpose!r}. "
            f"Allowed: {SUPPORTED_PURPOSES}."
        )
    return await _run_analyzer(
        ctx,
        asset_ids=[input.asset_id],
        purpose=input.purpose,
        focus=input.focus,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. analyze_site_photo
# ─────────────────────────────────────────────────────────────────────


class AnalyzeSitePhotoInput(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    focus: str = Field(default="", max_length=500)


@tool(
    name="analyze_site_photo",
    description=(
        "Read a site photo and produce a structured site-survey "
        "report — orientation, surroundings, lighting, vegetation, "
        "scale clues, watch-outs. Wraps analyze_image with "
        "purpose='site_photo'. Read-only."
    ),
    timeout_seconds=90.0,
)
async def analyze_site_photo(
    ctx: ToolContext,
    input: AnalyzeSitePhotoInput,
) -> VisionAnalysisOutput:
    return await _run_analyzer(
        ctx,
        asset_ids=[input.asset_id],
        purpose="site_photo",
        focus=input.focus,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. extract_aesthetic
# ─────────────────────────────────────────────────────────────────────


class ExtractAestheticInput(BaseModel):
    asset_ids: list[str] = Field(
        description=(
            "One or more reference image asset_ids. With 1 id the "
            "output is a single-image aesthetic read; with 2-8 ids "
            "the model treats them as a mood board and synthesises "
            "ONE common aesthetic."
        ),
        min_length=1,
        max_length=8,
    )
    focus: str = Field(default="", max_length=500)


@tool(
    name="extract_aesthetic",
    description=(
        "Extract the aesthetic (palette, materials, era, style tags, "
        "signature moves) from one or more reference images. With "
        "multiple images the model synthesises a single mood-board "
        "brief. Wraps analyze_image with purpose='reference' for "
        "1 image or 'mood_board' for 2+. Read-only."
    ),
    timeout_seconds=120.0,
)
async def extract_aesthetic(
    ctx: ToolContext,
    input: ExtractAestheticInput,
) -> VisionAnalysisOutput:
    purpose = "reference" if len(input.asset_ids) == 1 else "mood_board"
    return await _run_analyzer(
        ctx,
        asset_ids=input.asset_ids,
        purpose=purpose,
        focus=input.focus,
        max_tokens=1800,
    )


# ─────────────────────────────────────────────────────────────────────
# 4. sketch_to_floor_plan
# ─────────────────────────────────────────────────────────────────────


class SketchToFloorPlanInput(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    focus: str = Field(
        default="",
        max_length=500,
        description=(
            "Optional context — 'this is a 6x4m living room with "
            "north-facing windows'. Helps the model anchor "
            "dimensions when the sketch is ambiguous."
        ),
    )


@tool(
    name="sketch_to_floor_plan",
    description=(
        "Convert a hand-drawn sketch into a structured DesignGraph "
        "(room shape + dimensions in metres, furniture / fixture "
        "objects with positions, openings). Output is rough — the "
        "agent should treat low-confidence reads as a starting point "
        "and confirm dimensions with the user. Wraps analyze_image "
        "with purpose='hand_sketch'. Read-only."
    ),
    timeout_seconds=90.0,
)
async def sketch_to_floor_plan(
    ctx: ToolContext,
    input: SketchToFloorPlanInput,
) -> VisionAnalysisOutput:
    return await _run_analyzer(
        ctx,
        asset_ids=[input.asset_id],
        purpose="hand_sketch",
        focus=input.focus,
        max_tokens=1800,
    )


# ─────────────────────────────────────────────────────────────────────
# 5. digitize_floor_plan
# ─────────────────────────────────────────────────────────────────────


class DigitizeFloorPlanInput(BaseModel):
    asset_id: str = Field(min_length=1, max_length=120)
    focus: str = Field(default="", max_length=500)


@tool(
    name="digitize_floor_plan",
    description=(
        "Digitise a printed / scanned floor plan into a structured "
        "DesignGraph — room labels, dimensions in metres, openings "
        "(doors, windows) with widths and wall positions. The plan is "
        "treated as authoritative; the model is precise rather than "
        "creative. Wraps analyze_image with "
        "purpose='existing_floor_plan'. Read-only."
    ),
    timeout_seconds=120.0,
)
async def digitize_floor_plan(
    ctx: ToolContext,
    input: DigitizeFloorPlanInput,
) -> VisionAnalysisOutput:
    return await _run_analyzer(
        ctx,
        asset_ids=[input.asset_id],
        purpose="existing_floor_plan",
        focus=input.focus,
        max_tokens=2000,
    )
