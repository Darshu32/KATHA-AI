"""Stage 4E — drawing-generation tools (BRD Layer 5: drawing pack).

Five LLM-heavy tools that wrap the existing drawing services so the
agent can author a full architectural drawing pack as part of a chat
turn. Each tool produces:

- a structured **drawing spec** (the JSON the LLM authored — what to
  dimension, which hatches to apply, where to cut, etc.); and
- a **rendered SVG** ready to drop into the chat surface, an export
  pack, or a PDF.

The 5 tools mirror the BRD drawing types:

- :func:`generate_plan_view_drawing` — top-down room/piece plan with
  scale, key dimensions, section refs, material zones.
- :func:`generate_elevation_view_drawing` — front/side elevation of a
  furniture piece (or a room wall) with height / width dimensions,
  ergonomic targets, hardware callouts.
- :func:`generate_section_view_drawing` — cut-through section
  showing layer stack, joinery, foam/upholstery, reinforcement.
- :func:`generate_detail_sheet_drawing` — multi-cell zoom-in sheet
  (joints, edges, seams, hardware, material transitions).
- :func:`generate_isometric_view_drawing` — full-piece iso /
  perspective with optional exploded view + finish callouts.

Each tool:

1. Validates LLM input via Pydantic.
2. Builds the matching service request.
3. Calls the existing service generator (one OpenAI round-trip + an
   in-process SVG render).
4. Translates ``*ViewError`` / ``*SheetError`` into :class:`ToolError`
   so the agent gets a structured error envelope.
5. Returns the full structured spec + the rendered SVG + a slim
   validation summary.

Why these wrap pre-existing services
------------------------------------
The drawing services (``app.services.*_drawing_service``) already
encapsulate the prompt, knowledge build, validation, *and* the
SVG renderer. The tool layer is intentionally thin: descriptions
the LLM can reason about, plus a structured-error envelope.
Business logic stays where it was.

Cost guardrails
---------------
Every call hits the LLM. Per-tool timeout is 120 s — slightly more
generous than the Stage 4D spec tools because drawing prompts often
emit longer JSON (key dimensions, callouts, material zones).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.detail_sheet_drawing_service import (
    DetailSheetError,
    DetailSheetRequest,
    generate_detail_sheet_drawing as _generate_detail_sheet_drawing,
)
from app.services.elevation_view_drawing_service import (
    ElevationPiece,
    ElevationViewError,
    ElevationViewRequest,
    generate_elevation_view_drawing as _generate_elevation_view_drawing,
)
from app.services.isometric_view_drawing_service import (
    IsometricViewError,
    IsometricViewRequest,
    generate_isometric_view_drawing as _generate_isometric_view_drawing,
)
from app.services.plan_view_drawing_service import (
    PlanViewError,
    PlanViewRequest,
    generate_plan_view_drawing as _generate_plan_view_drawing,
)
from app.services.section_view_drawing_service import (
    SectionViewError,
    SectionViewRequest,
    generate_section_view_drawing as _generate_section_view_drawing,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared models
# ─────────────────────────────────────────────────────────────────────


class ElevationPieceInput(BaseModel):
    """Mirrors :class:`app.services.elevation_view_drawing_service.ElevationPiece`.

    Used by the elevation / section / detail / isometric tools to
    describe the furniture piece being drawn. Defaults match the
    service so the LLM can omit any field it doesn't have a value for.
    """

    type: str = Field(
        default="lounge_chair",
        max_length=64,
        description=(
            "Furniture archetype slug — lounge_chair, dining_chair, sofa, "
            "dining_table, coffee_table, bed, wardrobe, sideboard, etc. "
            "Drives the ergonomic envelope lookup."
        ),
    )
    dimensions_mm: Optional[dict[str, float]] = Field(
        default=None,
        description=(
            "Optional explicit overall dims as a dict with keys "
            "'length' / 'width' / 'height' in mm. Falls back to "
            "ergonomic-envelope mid-points when omitted."
        ),
    )
    ergonomic_targets_mm: Optional[dict[str, float]] = Field(
        default=None,
        description=(
            "Optional ergonomic target overrides — seat_height_mm, "
            "back_height_mm, leg_base_mm, arm_height_mm, seat_depth_mm. "
            "Mid-points of the BRD envelope are used when omitted."
        ),
    )
    material_hatch_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional hatch-vocabulary key for the primary material "
            "(e.g. 'wood_walnut', 'metal_brass', 'fabric_boucle'). "
            "Drives the SVG render's surface fill."
        ),
    )
    leg_base_hatch_key: Optional[str] = Field(
        default=None,
        description="Optional hatch key for the leg / base material.",
    )


def _to_elevation_piece(p: Optional[ElevationPieceInput]) -> Optional[ElevationPiece]:
    """Translate the agent-tool input into the service's BaseModel."""
    if p is None:
        return None
    return ElevationPiece(
        type=p.type,
        dimensions_mm=p.dimensions_mm,
        ergonomic_targets_mm=p.ergonomic_targets_mm,
        material_hatch_key=p.material_hatch_key,
        leg_base_hatch_key=p.leg_base_hatch_key,
    )


def _summarise_validation(validation: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Reduce a service-style validation dict to (passed, failed_flags).

    Mirror of the Stage 4D helper — copied so this module stays
    self-contained and the two stages can evolve independently.
    """
    if not validation:
        return True, []
    failed: list[str] = []
    for key, value in validation.items():
        if isinstance(value, bool) and value is False:
            failed.append(key)
    return (len(failed) == 0), failed


# Common fields shared across all 5 outputs. We don't compose via
# inheritance (Pydantic v2 handles it but the JSON schema is cleaner
# when each output declares fields directly).


# ─────────────────────────────────────────────────────────────────────
# 1. generate_plan_view_drawing
# ─────────────────────────────────────────────────────────────────────


class GeneratePlanViewInput(BaseModel):
    theme: str = Field(
        description="Theme slug. Required — every drawing is theme-grounded.",
        min_length=2,
        max_length=64,
    )
    design_graph: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Stage 3A design graph (rooms, walls, objects with positions + "
            "dimensions). Preferred input for room-scale plans."
        ),
    )
    parametric_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional parametric spec — used as fallback when design_graph is absent.",
    )
    project_summary: str = Field(
        default="",
        max_length=2000,
        description="Short project context the LLM weaves into the sheet narrative.",
    )
    sheet_title: str = Field(default="Plan View", max_length=120)
    canvas_width: int = Field(default=1100, ge=480, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


class DrawingOutput(BaseModel):
    """Common shape for all 5 drawing tools."""

    id: str
    name: str
    format: str = Field(default="svg")
    theme: str
    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    spec: dict[str, Any] = Field(
        description="The full structured drawing spec the LLM authored.",
    )
    svg: str = Field(description="Rendered SVG markup for the drawing.")
    meta: dict[str, Any] = Field(default_factory=dict)


@tool(
    name="generate_plan_view_drawing",
    description=(
        "Author the BRD plan view (top-down) for a room or piece — "
        "scale, key dimensions, section reference lines, material zones "
        "with hatch keys, and a sheet narrative. Calls the LLM plan "
        "author and renders the SVG. Use when the user asks for a "
        '"plan", "floor plan", or top-down sheet. Pass the Stage 3A '
        "design_graph for room-scale plans; parametric_spec works for "
        "single-piece plans."
    ),
    timeout_seconds=120.0,
    audit_target_type="plan_view_drawing",
)
async def generate_plan_view_drawing(
    ctx: ToolContext,
    input: GeneratePlanViewInput,
) -> DrawingOutput:
    req = PlanViewRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        sheet_title=input.sheet_title,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_plan_view_drawing(req)
    except PlanViewError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("plan_view_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DrawingOutput(
        id=str(result.get("id") or "plan_view"),
        name=str(result.get("name") or "Plan View"),
        format=str(result.get("format") or "svg"),
        theme=input.theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 2. generate_elevation_view_drawing
# ─────────────────────────────────────────────────────────────────────


class GenerateElevationViewInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: Optional[ElevationPieceInput] = Field(
        default=None,
        description=(
            "Furniture-scale input — preferred path. Provide piece.type "
            "and optional dimensions / hatch keys. Falls back to "
            "design_graph / parametric_spec when omitted."
        ),
    )
    design_graph: Optional[dict[str, Any]] = Field(
        default=None,
        description="Stage 3A design graph — used for room-scale wall elevations.",
    )
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    view: str = Field(
        default="front",
        max_length=16,
        description="Which face to elevate — 'front' or 'side'.",
    )
    sheet_title: str = Field(default="Elevation View", max_length=120)
    canvas_width: int = Field(default=1100, ge=480, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


@tool(
    name="generate_elevation_view_drawing",
    description=(
        "Author the BRD elevation view (front/side projection) for a "
        "furniture piece or wall — height + width dimensions, ergonomic "
        "targets called out (seat height, back height, arm height), "
        "hardware callouts, hatch keys for material zones. Calls the "
        "LLM elevation author and renders the SVG. Pass a `piece` for "
        "a single-piece elevation; pass `design_graph` for a room-wall "
        "elevation."
    ),
    timeout_seconds=120.0,
    audit_target_type="elevation_view_drawing",
)
async def generate_elevation_view_drawing(
    ctx: ToolContext,
    input: GenerateElevationViewInput,
) -> DrawingOutput:
    req = ElevationViewRequest(
        theme=input.theme,
        piece=_to_elevation_piece(input.piece),
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        view=input.view,
        sheet_title=input.sheet_title,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_elevation_view_drawing(req)
    except ElevationViewError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("elevation_view_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DrawingOutput(
        id=str(result.get("id") or "elevation_view"),
        name=str(result.get("name") or "Elevation View"),
        format=str(result.get("format") or "svg"),
        theme=input.theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 3. generate_section_view_drawing
# ─────────────────────────────────────────────────────────────────────


class GenerateSectionViewInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: Optional[ElevationPieceInput] = Field(
        default=None,
        description=(
            "Furniture piece to section through. Provide at minimum "
            "the type slug; dimensions fall back to ergonomic envelope "
            "mid-points if omitted."
        ),
    )
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    cut_label: str = Field(
        default="A-A",
        max_length=8,
        description="Section bubble label — usually 'A-A', 'B-B', etc.",
    )
    view_target: str = Field(
        default="through_seat",
        max_length=64,
        description=(
            "Where to cut — 'through_seat', 'through_arm', 'through_leg' "
            "for chairs/sofas; tables/cabinets accept 'through_top', "
            "'through_drawer'. Drives the layer-stack the LLM annotates."
        ),
    )
    sheet_title: str = Field(default="Section View", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=760, ge=320, le=2200)


@tool(
    name="generate_section_view_drawing",
    description=(
        "Author the BRD section view (cut-through) for a furniture piece "
        "— shows the layer stack (frame, foam, upholstery, finish), "
        "joinery + tolerances, reinforcement points, and the joinery "
        "callouts at scale. Calls the LLM section author and renders "
        'the SVG. Use when the user asks for a "section", "cut-through" '
        'or "show me how it is layered".'
    ),
    timeout_seconds=120.0,
    audit_target_type="section_view_drawing",
)
async def generate_section_view_drawing(
    ctx: ToolContext,
    input: GenerateSectionViewInput,
) -> DrawingOutput:
    req = SectionViewRequest(
        theme=input.theme,
        piece=_to_elevation_piece(input.piece),
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        cut_label=input.cut_label,
        view_target=input.view_target,
        sheet_title=input.sheet_title,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_section_view_drawing(req)
    except SectionViewError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("section_view_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DrawingOutput(
        id=str(result.get("id") or "section_view"),
        name=str(result.get("name") or "Section View"),
        format=str(result.get("format") or "svg"),
        theme=input.theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 4. generate_detail_sheet_drawing
# ─────────────────────────────────────────────────────────────────────


class GenerateDetailSheetInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: Optional[ElevationPieceInput] = Field(
        default=None,
        description=(
            "Furniture piece the detail cells zoom into. The LLM picks "
            "4–9 cells covering joints, edges, seams, hardware, and "
            "material transitions."
        ),
    )
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    sheet_title: str = Field(default="Detail Sheet", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=820, ge=320, le=2200)


@tool(
    name="generate_detail_sheet_drawing",
    description=(
        "Author the BRD detail sheet — a multi-cell page of zoomed-in "
        "construction details: joinery joints, edge profiles, seams, "
        "hardware mounts, material transitions. Each cell carries "
        "scale + tolerance + a short note. Calls the LLM detail-sheet "
        "author and renders the SVG. Use when production needs "
        "buildability information that doesn't fit on the elevation "
        "or section."
    ),
    timeout_seconds=120.0,
    audit_target_type="detail_sheet_drawing",
)
async def generate_detail_sheet_drawing(
    ctx: ToolContext,
    input: GenerateDetailSheetInput,
) -> DrawingOutput:
    req = DetailSheetRequest(
        theme=input.theme,
        piece=_to_elevation_piece(input.piece),
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        sheet_title=input.sheet_title,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_detail_sheet_drawing(req)
    except DetailSheetError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("detail_sheet_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DrawingOutput(
        id=str(result.get("id") or "detail_sheet"),
        name=str(result.get("name") or "Detail Sheet"),
        format=str(result.get("format") or "svg"),
        theme=input.theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 5. generate_isometric_view_drawing
# ─────────────────────────────────────────────────────────────────────


class GenerateIsometricViewInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    piece: Optional[ElevationPieceInput] = Field(
        default=None,
        description="Furniture piece to project. Required for piece-scale isos.",
    )
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    view_mode: str = Field(
        default="iso",
        max_length=16,
        description=(
            "Projection mode — 'iso' (true isometric) or 'perspective'. "
            "Iso preserves measured proportions; perspective is more "
            "presentation-friendly."
        ),
    )
    explode_enabled: bool = Field(
        default=False,
        description=(
            "If True, the LLM produces an exploded-view spec (parts "
            "displaced along their assembly axis) for fabrication briefs."
        ),
    )
    sheet_title: str = Field(default="Isometric View", max_length=120)
    canvas_width: int = Field(default=1200, ge=480, le=2400)
    canvas_height: int = Field(default=760, ge=320, le=2200)


@tool(
    name="generate_isometric_view_drawing",
    description=(
        "Author the BRD isometric / 3D sheet for a furniture piece — "
        "full-piece visualisation, parts breakdown (with optional "
        "exploded view), material finishes, and dimensions worth "
        "superimposing on the projection. Calls the LLM isometric "
        "author and renders the SVG. Use for client presentations "
        "or production assembly briefs (set explode_enabled=true)."
    ),
    timeout_seconds=120.0,
    audit_target_type="isometric_view_drawing",
)
async def generate_isometric_view_drawing(
    ctx: ToolContext,
    input: GenerateIsometricViewInput,
) -> DrawingOutput:
    req = IsometricViewRequest(
        theme=input.theme,
        piece=_to_elevation_piece(input.piece),
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        view_mode=input.view_mode,
        explode_enabled=input.explode_enabled,
        sheet_title=input.sheet_title,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_isometric_view_drawing(req)
    except IsometricViewError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("isometric_view_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DrawingOutput(
        id=str(result.get("id") or "isometric_view"),
        name=str(result.get("name") or "Isometric View"),
        format=str(result.get("format") or "svg"),
        theme=input.theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )
