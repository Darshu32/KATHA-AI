"""Stage 4G — generation-pipeline tools.

Five tools that wrap the project-scoped generation pipeline so the
agent can do the *core* design work in chat — not just describe or
analyse, but actually call the AI orchestrator and persist new
design-graph versions.

Pipeline tools (write — LLM round-trip + DB write per call):

- :func:`generate_initial_design` — run the full initial-generation
  pipeline from a prompt (room type + style + camera + lighting +
  drawing flags). Persists v1.
- :func:`apply_theme` — run the theme-switch pipeline against the
  latest design-graph version. Persists a new version.
- :func:`edit_design_object` — edit a single object via prompt
  ("make the dining table 1.8 m long"). Persists a new version.

Inspection tools (read-only):

- :func:`list_design_versions` — show the version history for the
  current project — the agent can answer "what versions do I have
  for this project?"
- :func:`validate_current_design` — run the BRD/NBC knowledge
  validator on the latest stored version. Returns errors + warnings
  + suggestions.

Project scoping
---------------
Every tool reads ``ctx.project_id`` and refuses to run without it —
the agent loop is responsible for setting that on the
:class:`~app.agents.tool.ToolContext` for the current chat session.
This prevents the LLM from accidentally redirecting calls to a
different project.

Cost guardrails
---------------
The 3 LLM-heavy tools have generous timeouts (180 s for initial
generation, 120 s for theme/edit). The 2 read tools sit at 30 s.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.design_graph_service import (
    get_latest_version,
    list_versions,
)
from app.services.generation_pipeline import (
    run_initial_generation as _run_initial_generation,
    run_local_edit as _run_local_edit,
    run_theme_switch as _run_theme_switch,
)
from app.services.knowledge_validator import (
    validate_design_graph as _validate_design_graph,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


def _require_project(ctx: ToolContext) -> str:
    """Pull ``project_id`` off the context or raise ToolError."""
    project_id = ctx.project_id
    if not project_id:
        raise ToolError(
            "No project_id on the agent context. The pipeline tools "
            "require a project scope — open a project first or pass "
            "project_id when starting the chat session."
        )
    return project_id


def _summarise_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Slim view of a design graph for LLM consumption.

    The full graph is preserved separately under ``full_graph_data`` so
    the agent can pass it to subsequent drawing / diagram tools without
    a re-fetch round-trip.
    """
    if not isinstance(graph, dict):
        return {}
    room = graph.get("room") or (graph.get("spaces") or [{}])[0] or {}
    dims = room.get("dimensions") or {}
    objects = graph.get("objects") or []
    object_types = sorted({(o.get("type") or "").lower() for o in objects if o.get("type")})
    materials = graph.get("materials") or []

    style = graph.get("style") or {}
    style_primary = style.get("primary") if isinstance(style, dict) else None

    return {
        "room_type": room.get("type") or graph.get("room_type"),
        "room_dimensions_m": {
            "length": dims.get("length"),
            "width": dims.get("width"),
            "height": dims.get("height"),
        },
        "object_count": len(objects),
        "object_types": object_types,
        "material_count": len(materials),
        "style_primary": style_primary,
    }


def _summarise_estimate(estimate: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Slim cost view from the estimation_engine output."""
    if not isinstance(estimate, dict):
        return {}
    # The estimation_engine output is heterogeneous — pull the most
    # commonly useful keys without making this brittle.
    return {
        "total": estimate.get("total")
            or estimate.get("retail_total")
            or estimate.get("manufacturing_total"),
        "currency": estimate.get("currency") or "INR",
        "summary": estimate.get("summary"),
    }


# ─────────────────────────────────────────────────────────────────────
# 1. generate_initial_design
# ─────────────────────────────────────────────────────────────────────


class GenerateInitialDesignInput(BaseModel):
    """LLM input for the initial-generation pipeline."""

    prompt: str = Field(
        description=(
            "Free-text design brief — the architect's request in plain "
            "English. The AI orchestrator turns this into a structured "
            "design graph (rooms, walls, objects, materials, lighting). "
            "Be specific: dimensions, style cues, must-haves."
        ),
        min_length=10,
        max_length=5000,
    )
    room_type: str = Field(
        default="living_room",
        max_length=64,
        description=(
            "Primary room type — living_room, bedroom, kitchen, dining_room, "
            "office, bathroom, etc."
        ),
    )
    style: str = Field(
        default="modern",
        max_length=64,
        description=(
            "Theme slug — modern | mid_century_modern | pedestal | "
            "scandinavian | industrial | minimalist | traditional | luxe."
        ),
    )
    camera: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional camera framing for renders — eye_level / iso / orbit.",
    )
    lighting: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional lighting prefset — daylight / studio / dusk.",
    )
    view_mode: Optional[str] = Field(default=None, max_length=64)
    ratio: Optional[str] = Field(default=None, max_length=16)
    quality: Optional[str] = Field(default=None, max_length=32)
    drawing_type: Optional[str] = Field(default=None, max_length=64)


class GenerationOutput(BaseModel):
    """Common shape for generate / theme / edit responses."""

    project_id: str
    version: int
    version_id: str
    change_type: str
    change_summary: str
    status: str = Field(default="completed")
    graph_summary: dict[str, Any] = Field(default_factory=dict)
    estimate_summary: dict[str, Any] = Field(default_factory=dict)
    full_graph_data: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Full design graph for the new version. Keep available so the "
            "agent can chain drawing / diagram / spec tools without a "
            "re-fetch. Large — only inspect via slicing when reasoning."
        ),
    )
    changed_object_ids: list[str] = Field(default_factory=list)


@tool(
    name="generate_initial_design",
    description=(
        "Run the full initial-generation pipeline for the current "
        "project: AI orchestrates a structured design graph from the "
        "prompt, persists it as version 1, and computes an estimate. "
        "Use when the user says 'design me X' or 'start a new project'. "
        "Requires a project to be in scope on the chat session."
    ),
    timeout_seconds=180.0,
    audit_target_type="design_graph",
)
async def generate_initial_design(
    ctx: ToolContext,
    input: GenerateInitialDesignInput,
) -> GenerationOutput:
    project_id = _require_project(ctx)
    try:
        result = await _run_initial_generation(
            db=ctx.session,
            project_id=project_id,
            prompt=input.prompt,
            room_type=input.room_type,
            style=input.style,
            camera=input.camera,
            lighting=input.lighting,
            view_mode=input.view_mode,
            ratio=input.ratio,
            quality=input.quality,
            drawing_type=input.drawing_type,
        )
    except (ValueError, RuntimeError) as exc:
        raise ToolError(f"Initial generation failed: {exc}") from exc

    graph = result.get("graph_data") or {}
    return GenerationOutput(
        project_id=str(result.get("project_id") or project_id),
        version=int(result.get("version") or 0),
        version_id=str(result.get("version_id") or ""),
        change_type="initial",
        change_summary=f"Initial generation from prompt: {input.prompt[:100]}",
        status=str(result.get("status") or "completed"),
        graph_summary=_summarise_graph(graph),
        estimate_summary=_summarise_estimate(result.get("estimate")),
        full_graph_data=graph,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. apply_theme
# ─────────────────────────────────────────────────────────────────────


class ApplyThemeInput(BaseModel):
    """LLM input for the theme-switch pipeline."""

    new_style: str = Field(
        description=(
            "Target theme slug — modern | mid_century_modern | pedestal | "
            "scandinavian | industrial | minimalist | traditional | luxe. "
            "The AI re-skins the current design graph against this theme."
        ),
        min_length=2,
        max_length=64,
    )
    preserve_layout: bool = Field(
        default=True,
        description=(
            "If True, keeps room dimensions + object positions unchanged "
            "and only swaps materials / colours / hardware. If False, the "
            "AI may reshape the layout to suit the new theme."
        ),
    )


@tool(
    name="apply_theme",
    description=(
        "Run the theme-switch pipeline: re-skin the latest design-graph "
        "version of the current project under a new theme. Persists a new "
        'version with change_type="theme_switch". Use when the user says '
        "'try this in scandinavian' or 'change the theme to industrial'. "
        "Requires a project + at least one prior version in scope."
    ),
    timeout_seconds=120.0,
    audit_target_type="design_graph",
)
async def apply_theme(
    ctx: ToolContext,
    input: ApplyThemeInput,
) -> GenerationOutput:
    project_id = _require_project(ctx)
    try:
        result = await _run_theme_switch(
            db=ctx.session,
            project_id=project_id,
            new_style=input.new_style,
            preserve_layout=input.preserve_layout,
        )
    except ValueError as exc:
        # The pipeline raises ValueError on "no versions found".
        raise ToolError(str(exc)) from exc
    except RuntimeError as exc:
        raise ToolError(f"Theme switch failed: {exc}") from exc

    graph = result.get("graph_data") or {}
    return GenerationOutput(
        project_id=str(result.get("project_id") or project_id),
        version=int(result.get("version") or 0),
        version_id=str(result.get("version_id") or ""),
        change_type="theme_switch",
        change_summary=f"Theme switched to {input.new_style}",
        status=str(result.get("status") or "completed"),
        graph_summary=_summarise_graph(graph),
        estimate_summary=_summarise_estimate(result.get("estimate")),
        full_graph_data=graph,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. edit_design_object
# ─────────────────────────────────────────────────────────────────────


class EditDesignObjectInput(BaseModel):
    """LLM input for the local-edit pipeline."""

    object_id: str = Field(
        description=(
            "ID of the object to edit — pulled from the latest graph's "
            "objects[].id. The agent typically gets this from a prior "
            "tool call (list_design_versions / drawings) or from the "
            "user pointing at it."
        ),
        min_length=1,
        max_length=120,
    )
    edit_prompt: str = Field(
        description=(
            "Free-text edit request — 'make this 1.8 m long', 'swap to "
            "walnut', 'rotate 90 degrees'. The AI applies the change to "
            "the named object and returns an updated graph."
        ),
        min_length=5,
        max_length=2000,
    )


@tool(
    name="edit_design_object",
    description=(
        "Edit a single object in the latest version of the current "
        "project's design graph via a free-text prompt. Persists a new "
        'version with change_type="prompt_edit". Use for targeted '
        "changes the user requests — 'make the table longer', 'swap the "
        "chair material', etc. Requires a project + at least one prior "
        "version."
    ),
    timeout_seconds=90.0,
    audit_target_type="design_graph",
)
async def edit_design_object(
    ctx: ToolContext,
    input: EditDesignObjectInput,
) -> GenerationOutput:
    project_id = _require_project(ctx)
    try:
        result = await _run_local_edit(
            db=ctx.session,
            project_id=project_id,
            object_id=input.object_id,
            edit_prompt=input.edit_prompt,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except RuntimeError as exc:
        raise ToolError(f"Local edit failed: {exc}") from exc

    graph = result.get("graph_data") or {}
    return GenerationOutput(
        project_id=str(result.get("project_id") or project_id),
        version=int(result.get("version") or 0),
        version_id=str(result.get("version_id") or ""),
        change_type="prompt_edit",
        change_summary=f"Edited {input.object_id}: {input.edit_prompt[:100]}",
        status=str(result.get("status") or "completed"),
        graph_summary=_summarise_graph(graph),
        estimate_summary=_summarise_estimate(result.get("estimate")),
        full_graph_data=graph,
        changed_object_ids=list(result.get("changed_objects") or [input.object_id]),
    )


# ─────────────────────────────────────────────────────────────────────
# 4. list_design_versions
# ─────────────────────────────────────────────────────────────────────


class ListDesignVersionsInput(BaseModel):
    """No fields — project_id is read off ctx."""

    pass


class DesignVersionMeta(BaseModel):
    version: int
    version_id: str
    change_type: str
    change_summary: str
    created_at: Optional[str] = None
    changed_object_ids: list[str] = Field(default_factory=list)


class ListDesignVersionsOutput(BaseModel):
    project_id: str
    version_count: int
    latest_version: int
    versions: list[DesignVersionMeta] = Field(
        description="Newest first — call get_design_version for the full graph.",
    )


@tool(
    name="list_design_versions",
    description=(
        "List every persisted design-graph version for the current "
        "project — newest first. Returns version number, change_type, "
        "change_summary, created_at. Use when the user asks 'show me my "
        "design history' or to find a version_id to drill into. "
        "Requires a project in scope."
    ),
    timeout_seconds=30.0,
)
async def list_design_versions(
    ctx: ToolContext,
    input: ListDesignVersionsInput,
) -> ListDesignVersionsOutput:
    project_id = _require_project(ctx)
    versions = await list_versions(ctx.session, project_id)

    metas: list[DesignVersionMeta] = []
    for v in versions:
        created = getattr(v, "created_at", None)
        metas.append(
            DesignVersionMeta(
                version=int(getattr(v, "version", 0)),
                version_id=str(getattr(v, "id", "")),
                change_type=str(getattr(v, "change_type", "") or ""),
                change_summary=str(getattr(v, "change_summary", "") or ""),
                created_at=created.isoformat() if hasattr(created, "isoformat") else None,
                changed_object_ids=list(getattr(v, "changed_object_ids", None) or []),
            )
        )

    latest = max((m.version for m in metas), default=0)
    return ListDesignVersionsOutput(
        project_id=project_id,
        version_count=len(metas),
        latest_version=latest,
        versions=metas,
    )


# ─────────────────────────────────────────────────────────────────────
# 5. validate_current_design
# ─────────────────────────────────────────────────────────────────────


class ValidateCurrentDesignInput(BaseModel):
    segment: str = Field(
        default="residential",
        max_length=32,
        description=(
            "Building segment for the validator — 'residential' or "
            "'commercial'. Drives which BRD/NBC space-area thresholds "
            "are applied."
        ),
    )


class ValidationIssue(BaseModel):
    code: str
    path: str
    message: str


class ValidateCurrentDesignOutput(BaseModel):
    project_id: str
    version: int
    ok: bool
    summary: str
    error_count: int
    warning_count: int
    suggestion_count: int
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    suggestions: list[ValidationIssue] = Field(default_factory=list)


@tool(
    name="validate_current_design",
    description=(
        "Run the BRD/NBC knowledge validator on the latest stored "
        "version of the current project. Returns ok flag + errors + "
        "warnings + suggestions covering room area, NBC compliance, "
        "ergonomic ranges, theme palette drift, door clearances, "
        "structural span limits, MEP sanity, and manufacturing "
        "feasibility. Use after a generate / edit / theme-switch to "
        'close the loop, or when the user asks "is this compliant?". '
        "Requires a project + at least one prior version."
    ),
    timeout_seconds=30.0,
)
async def validate_current_design(
    ctx: ToolContext,
    input: ValidateCurrentDesignInput,
) -> ValidateCurrentDesignOutput:
    project_id = _require_project(ctx)
    latest = await get_latest_version(ctx.session, project_id)
    if latest is None:
        raise ToolError(
            f"No design-graph versions found for project {project_id}. "
            "Run generate_initial_design first."
        )

    graph = getattr(latest, "graph_data", {}) or {}
    report = _validate_design_graph(graph, segment=input.segment)

    def _to_issues(items: list[dict[str, Any]]) -> list[ValidationIssue]:
        return [
            ValidationIssue(
                code=str(i.get("code") or ""),
                path=str(i.get("path") or ""),
                message=str(i.get("message") or ""),
            )
            for i in (items or [])
        ]

    errors = _to_issues(report.get("errors") or [])
    warnings = _to_issues(report.get("warnings") or [])
    suggestions = _to_issues(report.get("suggestions") or [])

    return ValidateCurrentDesignOutput(
        project_id=project_id,
        version=int(getattr(latest, "version", 0)),
        ok=bool(report.get("ok")),
        summary=str(report.get("summary") or ""),
        error_count=len(errors),
        warning_count=len(warnings),
        suggestion_count=len(suggestions),
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )
