"""Stage 4F — diagram-generation tools (BRD Layer 2B: 8 diagram types).

Eight LLM-heavy tools that wrap the existing diagram services so the
agent can author conceptual / analytical diagrams in a chat turn.
Each call produces:

- a structured **diagram spec** (the JSON the LLM authored — zone
  assignments, hierarchy tiers, signature moves, watch-outs, etc.); and
- a **rendered SVG** (deterministic base + LLM-driven annotations)
  ready to drop into the chat surface or an export pack.

The 8 tools mirror the BRD diagram catalogue (`/diagrams/types`):

1. :func:`generate_concept_diagram` — Concept Transparency (BRD 2B #1):
   material/form relationship, functional zones, signature moves.
2. :func:`generate_form_diagram` — Form Development (BRD 2B #2):
   four-stage evolution (volume → grid → subtract → articulate).
3. :func:`generate_volumetric_diagram` — Volumetric Hierarchy (BRD 2B #3):
   silhouette, weight, space allocation, stacking logic.
4. :func:`generate_volumetric_block_diagram` — Volumetric Diagram (BRD 2B #4):
   3D block read with masses, voids, slicing strategy.
5. :func:`generate_design_process_diagram` — Design Process (BRD 2B #5):
   step-by-step decision narrative + rejected alternatives.
6. :func:`generate_solid_void_diagram` — Solid vs Void (BRD 2B #6):
   positive/negative space, weight pattern, breathing room.
7. :func:`generate_spatial_organism_diagram` — Spatial Organism (BRD 2B #7):
   how a body inhabits the space, movement choreography.
8. :func:`generate_hierarchy_diagram` — Hierarchy (BRD 2B #8):
   visual / material / functional tiers with emphasis rules.

Why these wrap pre-existing services
------------------------------------
The diagram services (``app.services.*_diagram_service``) already
encapsulate the prompt, knowledge build, validation, *and* the SVG
renderer (deterministic base + LLM annotations). The tool layer is
intentionally thin: descriptions the LLM can reason about, plus a
structured-error envelope and uniform output shape.

Cost guardrails
---------------
Every call hits the LLM. Per-tool timeout is 120 s — same as Stage 4E
drawings, since both share the LLM-+-render pattern. Canvas dims are
capped per the underlying service's bounds.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.concept_diagram_service import (
    ConceptDiagramError,
    ConceptDiagramRequest,
    generate_concept_diagram as _generate_concept_diagram,
)
from app.services.design_process_diagram_service import (
    DesignProcessError,
    DesignProcessRequest,
    generate_design_process_diagram as _generate_design_process_diagram,
)
from app.services.form_diagram_service import (
    FormDiagramError,
    FormDiagramRequest,
    generate_form_diagram as _generate_form_diagram,
)
from app.services.hierarchy_diagram_service import (
    HierarchyError,
    HierarchyRequest,
    generate_hierarchy_diagram as _generate_hierarchy_diagram,
)
from app.services.solid_void_diagram_service import (
    SolidVoidError,
    SolidVoidRequest,
    generate_solid_void_diagram as _generate_solid_void_diagram,
)
from app.services.spatial_organism_diagram_service import (
    SpatialOrganismError,
    SpatialOrganismRequest,
    generate_spatial_organism_diagram as _generate_spatial_organism_diagram,
)
from app.services.volumetric_block_diagram_service import (
    VolumetricBlockError,
    VolumetricBlockRequest,
    generate_volumetric_block_diagram as _generate_volumetric_block_diagram,
)
from app.services.volumetric_diagram_service import (
    VolumetricDiagramError,
    VolumetricDiagramRequest,
    generate_volumetric_diagram as _generate_volumetric_diagram,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared output + helpers
# ─────────────────────────────────────────────────────────────────────


class DiagramOutput(BaseModel):
    """Common shape for all 8 diagram tools — mirrors Stage 4E drawings."""

    id: str
    name: str
    format: str = Field(default="svg")
    theme: str
    validation_passed: bool
    validation_failures: list[str] = Field(
        default_factory=list,
        description="Names of validation flags that returned False (empty when no validation block).",
    )
    spec: dict[str, Any] = Field(
        description="The full structured diagram spec the LLM authored.",
    )
    svg: str = Field(description="Rendered SVG markup (deterministic base + LLM annotations).")
    meta: dict[str, Any] = Field(default_factory=dict)


def _summarise_validation(validation: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Reduce a service-style validation dict to (passed, failed_flags).

    Some diagram services emit no ``validation`` block at all — for
    those we return ``(True, [])`` so the agent doesn't see a noisy
    failure when there's nothing to fail.
    """
    if not validation:
        return True, []
    failed: list[str] = []
    for key, value in validation.items():
        if isinstance(value, bool) and value is False:
            failed.append(key)
    return (len(failed) == 0), failed


def _wrap_result(
    result: dict[str, Any],
    *,
    spec_key: str,
    default_id: str,
    default_name: str,
    theme: str,
) -> DiagramOutput:
    """Translate a service result dict into the uniform DiagramOutput."""
    spec = result.get(spec_key) or {}
    passed, failed = _summarise_validation(result.get("validation"))
    return DiagramOutput(
        id=str(result.get("id") or default_id),
        name=str(result.get("name") or default_name),
        format=str(result.get("format") or "svg"),
        theme=theme,
        validation_passed=passed,
        validation_failures=failed,
        spec=spec,
        svg=str(result.get("svg") or ""),
        meta=dict(result.get("meta") or {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 1. generate_concept_diagram  — BRD 2B #1
# ─────────────────────────────────────────────────────────────────────


class GenerateConceptDiagramInput(BaseModel):
    theme: str = Field(
        description="Theme slug. Required — concept rests on the theme palette.",
        min_length=2,
        max_length=64,
    )
    design_graph: Optional[dict[str, Any]] = Field(
        default=None,
        description="Stage 3A design graph — preferred input for room-scale concept reads.",
    )
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=320, le=2400)
    canvas_height: int = Field(default=600, ge=240, le=1800)


@tool(
    name="generate_concept_diagram",
    description=(
        "Author the BRD Concept Transparency diagram (BRD 2B #1) — the "
        "core design-intent read: material/form relationship, functional "
        "zones, signature moves, palette emphasis points. Calls the LLM "
        "concept author and renders the annotated SVG. Use when the "
        'user asks "what is the design idea here" or needs a one-page '
        "concept page for client kick-off."
    ),
    timeout_seconds=120.0,
    audit_target_type="concept_diagram",
)
async def generate_concept_diagram(
    ctx: ToolContext,
    input: GenerateConceptDiagramInput,
) -> DiagramOutput:
    req = ConceptDiagramRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_concept_diagram(req)
    except ConceptDiagramError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="concept_spec",
        default_id="concept_transparency",
        default_name="Concept Transparency",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. generate_form_diagram  — BRD 2B #2
# ─────────────────────────────────────────────────────────────────────


class GenerateFormDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=520, ge=240, le=1800)


@tool(
    name="generate_form_diagram",
    description=(
        "Author the BRD Form Development diagram (BRD 2B #2) — the "
        "four-stage evolution read: volume → grid → subtract → "
        "articulate, with theme signature moves called out per stage. "
        "Calls the LLM form author and renders the annotated 4-panel "
        "SVG. Use when the user wants to see how the form was reasoned "
        "into being."
    ),
    timeout_seconds=120.0,
    audit_target_type="form_diagram",
)
async def generate_form_diagram(
    ctx: ToolContext,
    input: GenerateFormDiagramInput,
) -> DiagramOutput:
    req = FormDiagramRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_form_diagram(req)
    except FormDiagramError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="form_spec",
        default_id="form_development",
        default_name="Form Development",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. generate_volumetric_diagram  — BRD 2B #3 (Volumetric Hierarchy)
# ─────────────────────────────────────────────────────────────────────


class GenerateVolumetricDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


@tool(
    name="generate_volumetric_diagram",
    description=(
        "Author the BRD Volumetric Hierarchy diagram (BRD 2B #3) — the "
        "vertical × horizontal read of the project: silhouette, weight "
        "distribution, space allocation, stacking logic. Calls the LLM "
        "volumetric author and renders the annotated axonometric SVG. "
        "Use to defend mass / proportion choices in a review."
    ),
    timeout_seconds=120.0,
    audit_target_type="volumetric_diagram",
)
async def generate_volumetric_diagram(
    ctx: ToolContext,
    input: GenerateVolumetricDiagramInput,
) -> DiagramOutput:
    req = VolumetricDiagramRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_volumetric_diagram(req)
    except VolumetricDiagramError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="volumetric_spec",
        default_id="volumetric_hierarchy",
        default_name="Volumetric Hierarchy",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 4. generate_volumetric_block_diagram  — BRD 2B #4 (Volumetric Diagram)
# ─────────────────────────────────────────────────────────────────────


class GenerateVolumetricBlockDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=1100, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


@tool(
    name="generate_volumetric_block_diagram",
    description=(
        "Author the BRD Volumetric (Block) diagram (BRD 2B #4) — the "
        "3D block read: masses, voids, spatial relationships, slicing "
        "strategy. Calls the LLM block author and renders the annotated "
        "axonometric SVG. Use when massing alternatives or void strategy "
        "needs to be made visible."
    ),
    timeout_seconds=120.0,
    audit_target_type="volumetric_block_diagram",
)
async def generate_volumetric_block_diagram(
    ctx: ToolContext,
    input: GenerateVolumetricBlockDiagramInput,
) -> DiagramOutput:
    req = VolumetricBlockRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_volumetric_block_diagram(req)
    except VolumetricBlockError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="volumetric_block_spec",
        default_id="volumetric_block",
        default_name="Volumetric Diagram",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 5. generate_design_process_diagram  — BRD 2B #5
# ─────────────────────────────────────────────────────────────────────


class GenerateDesignProcessDiagramInput(BaseModel):
    """Slightly wider input than the others — accepts an architect_brief
    so the LLM can narrate how brief → design decisions cascaded."""

    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    architect_brief: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional structured architect brief — the LLM uses it to "
            "show how brief → decisions → form cascaded. When omitted, "
            "the existing renderer step-log is used as the seed."
        ),
    )
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


@tool(
    name="generate_design_process_diagram",
    description=(
        "Author the BRD Design Process diagram (BRD 2B #5) — the step-"
        "by-step design narrative: decision points, rule drivers, "
        "rejected alternatives. Calls the LLM process author and renders "
        "the annotated flow SVG. Use for review boards or post-mortems "
        "where the *why* of each move needs to be defended."
    ),
    timeout_seconds=120.0,
    audit_target_type="design_process_diagram",
)
async def generate_design_process_diagram(
    ctx: ToolContext,
    input: GenerateDesignProcessDiagramInput,
) -> DiagramOutput:
    req = DesignProcessRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        architect_brief=input.architect_brief,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_design_process_diagram(req)
    except DesignProcessError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="design_process_spec",
        default_id="design_process",
        default_name="Design Process",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 6. generate_solid_void_diagram  — BRD 2B #6
# ─────────────────────────────────────────────────────────────────────


class GenerateSolidVoidDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


@tool(
    name="generate_solid_void_diagram",
    description=(
        "Author the BRD Solid vs Void diagram (BRD 2B #6) — the "
        "positive/negative space read: solid % vs void %, weight "
        "pattern, breathing room around objects, watch-outs against "
        "circulation minima. Calls the LLM solid/void author and "
        "renders the annotated plan SVG. Use when overcrowding or "
        "circulation tightness is a worry."
    ),
    timeout_seconds=120.0,
    audit_target_type="solid_void_diagram",
)
async def generate_solid_void_diagram(
    ctx: ToolContext,
    input: GenerateSolidVoidDiagramInput,
) -> DiagramOutput:
    req = SolidVoidRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_solid_void_diagram(req)
    except SolidVoidError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="solid_void_spec",
        default_id="solid_void",
        default_name="Solid vs Void",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 7. generate_spatial_organism_diagram  — BRD 2B #7
# ─────────────────────────────────────────────────────────────────────


class GenerateSpatialOrganismDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


@tool(
    name="generate_spatial_organism_diagram",
    description=(
        "Author the BRD Spatial Organism diagram (BRD 2B #7) — how a "
        "body inhabits the space: interaction touchpoints, movement "
        "choreography, usage patterns. Calls the LLM body-in-space "
        "author and renders the annotated plan SVG. Use to validate "
        "that the design actually works for the human using it."
    ),
    timeout_seconds=120.0,
    audit_target_type="spatial_organism_diagram",
)
async def generate_spatial_organism_diagram(
    ctx: ToolContext,
    input: GenerateSpatialOrganismDiagramInput,
) -> DiagramOutput:
    req = SpatialOrganismRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_spatial_organism_diagram(req)
    except SpatialOrganismError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="spatial_organism_spec",
        default_id="spatial_organism",
        default_name="Spatial Organism",
        theme=input.theme,
    )


# ─────────────────────────────────────────────────────────────────────
# 8. generate_hierarchy_diagram  — BRD 2B #8
# ─────────────────────────────────────────────────────────────────────


class GenerateHierarchyDiagramInput(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: Optional[dict[str, Any]] = Field(default=None)
    parametric_spec: Optional[dict[str, Any]] = Field(default=None)
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=620, ge=320, le=1800)


@tool(
    name="generate_hierarchy_diagram",
    description=(
        "Author the BRD Hierarchy diagram (BRD 2B #8) — three rankings: "
        "visual, material, functional, each with emphasis rules per "
        "tier. Calls the LLM three-rank hierarchy author and renders "
        "the annotated SVG. Use when the brief says 'what dominates "
        "what' is unclear, or to defend a featured-piece pick."
    ),
    timeout_seconds=120.0,
    audit_target_type="hierarchy_diagram",
)
async def generate_hierarchy_diagram(
    ctx: ToolContext,
    input: GenerateHierarchyDiagramInput,
) -> DiagramOutput:
    req = HierarchyRequest(
        theme=input.theme,
        design_graph=input.design_graph,
        parametric_spec=input.parametric_spec,
        project_summary=input.project_summary,
        canvas_width=input.canvas_width,
        canvas_height=input.canvas_height,
    )
    try:
        result = await _generate_hierarchy_diagram(req)
    except HierarchyError as exc:
        raise ToolError(str(exc)) from exc
    return _wrap_result(
        result,
        spec_key="hierarchy_spec",
        default_id="hierarchy",
        default_name="Hierarchy",
        theme=input.theme,
    )
