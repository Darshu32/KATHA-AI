"""AI orchestration for prompt-to-design-graph flows."""

import json
import logging
from copy import deepcopy

from openai import AsyncOpenAI

from app.config import get_settings
from app.models.design_graph import DesignGraph
from app.prompts.design_graph import DESIGN_GRAPH_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


def _has_openai_config() -> bool:
    return bool(settings.openai_api_key and settings.openai_api_key.strip())


DESIGN_GRAPH_JSON_SCHEMA = {
    "name": "design_graph",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "room": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "dimensions": {
                        "type": "object",
                        "properties": {
                            "length": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                        "required": ["length", "width", "height"],
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "dimensions"],
                "additionalProperties": False,
            },
            "style": {
                "type": "object",
                "properties": {
                    "primary": {"type": "string"},
                    "secondary": {"type": "array", "items": {"type": "string"}},
                    "color_palette": {"type": "array", "items": {"type": "string"}},
                    "materials": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["primary", "secondary", "color_palette", "materials"],
                "additionalProperties": False,
            },
            "objects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "name": {"type": "string"},
                        "position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "rotation": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "dimensions": {
                            "type": "object",
                            "properties": {
                                "length": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            },
                            "required": ["length", "width", "height"],
                            "additionalProperties": False,
                        },
                        "material": {"type": "string"},
                        "color": {"type": "string"},
                    },
                    "required": [
                        "id",
                        "type",
                        "name",
                        "position",
                        "rotation",
                        "dimensions",
                        "material",
                        "color",
                    ],
                    "additionalProperties": False,
                },
            },
            "materials": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "color": {"type": "string"},
                    },
                    "required": ["id", "name", "category", "color"],
                    "additionalProperties": False,
                },
            },
            "lighting": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "intensity": {"type": "number"},
                        "color": {"type": "string"},
                    },
                    "required": ["id", "type", "position", "intensity", "color"],
                    "additionalProperties": False,
                },
            },
            "render_prompt_2d": {"type": "string"},
            "render_prompt_3d": {"type": "string"},
        },
        "required": [
            "room",
            "style",
            "objects",
            "materials",
            "lighting",
            "render_prompt_2d",
            "render_prompt_3d",
        ],
        "additionalProperties": False,
    },
}


async def generate_design_graph(
    prompt: str,
    room_type: str = "living_room",
    style: str = "modern",
    project_id: str = "proj_new",
) -> DesignGraph:
    if not _has_openai_config():
        logger.warning(
            "OPENAI_API_KEY is not configured. Using local starter design graph."
        )
        return _build_local_design_graph(
            prompt=prompt,
            room_type=room_type,
            style=style,
            project_id=project_id,
        )

    client = _get_client()
    user_message = (
        f"Design prompt: {prompt}\n"
        f"Room type: {room_type}\n"
        f"Style/theme: {style}\n\n"
        "Generate the full structured design graph JSON."
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": DESIGN_GRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": DESIGN_GRAPH_JSON_SCHEMA,
        },
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    logger.info("AI design graph generated for project %s", project_id)
    return _ai_response_to_design_graph(data, project_id)


def _ai_response_to_design_graph(data: dict, project_id: str) -> DesignGraph:
    from app.models.design_graph import AssetBundle, DesignGraph, SiteInfo, StyleProfile

    room = data.get("room", {})
    style_data = data.get("style", {})
    dims = room.get("dimensions", {})

    return DesignGraph(
        project_id=project_id,
        version=1,
        design_type="interior",
        style=StyleProfile(
            primary=style_data.get("primary", "modern"),
            secondary=style_data.get("secondary", []),
        ),
        site=SiteInfo(unit="metric"),
        spaces=[
            {
                "id": "space_001",
                "name": room.get("type", "Room"),
                "room_type": room.get("type", "living_room"),
                "dimensions": dims,
                "objects": [obj["id"] for obj in data.get("objects", [])],
            }
        ],
        geometry=[],
        objects=data.get("objects", []),
        materials=data.get("materials", []),
        lighting=data.get("lighting", []),
        constraints=[],
        estimation={
            "status": "pending",
            "assumptions": ["Quantities will be computed after geometry is validated."],
        },
        assets=AssetBundle(
            render_2d=[],
            scene_3d=[],
            masks=[],
            render_prompt_2d=data.get("render_prompt_2d", ""),
            render_prompt_3d=data.get("render_prompt_3d", ""),
        ),
    )


async def edit_object_via_prompt(
    current_graph: dict,
    object_id: str,
    edit_prompt: str,
) -> dict:
    if not _has_openai_config():
        updated_graph = deepcopy(current_graph)
        for obj in updated_graph.get("objects", []):
            if obj.get("id") == object_id:
                metadata = obj.setdefault("metadata", {})
                metadata["last_edit_prompt"] = edit_prompt
                if "brick" in edit_prompt.lower():
                    obj["material"] = "mat_brick"
                    obj["color"] = "#9a5c45"
                elif "wood" in edit_prompt.lower():
                    obj["material"] = "mat_floor_oak"
                    obj["color"] = "#9b6b3d"
                break
        return updated_graph

    client = _get_client()

    target_obj = None
    for obj in current_graph.get("objects", []):
        if obj.get("id") == object_id:
            target_obj = obj
            break

    if target_obj is None:
        raise ValueError(f"Object {object_id} not found in design graph")

    user_message = (
        f"Current object:\n{json.dumps(target_obj, indent=2)}\n\n"
        f"Edit instruction: {edit_prompt}\n\n"
        "Return the updated object JSON only. Keep the same id and type. "
        "Only change what the instruction asks for."
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an architecture design AI. You receive a design object "
                    "and an edit instruction. Return ONLY the updated object as valid JSON. "
                    "Preserve the object's id and type. Apply realistic changes."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0.5,
        max_tokens=1024,
    )

    updated_obj = json.loads(response.choices[0].message.content)
    for index, obj in enumerate(current_graph["objects"]):
        if obj.get("id") == object_id:
            current_graph["objects"][index] = updated_obj
            break

    return current_graph


async def switch_theme(
    current_graph: dict,
    new_style: str,
    preserve_layout: bool = True,
) -> dict:
    if not _has_openai_config():
        updated_graph = deepcopy(current_graph)
        updated_graph["style"] = {
            "primary": new_style,
            "secondary": ["local-fallback"],
        }
        for obj in updated_graph.get("objects", []):
            if new_style == "spanish":
                obj["color"] = "#c96f4a" if obj.get("type") != "sofa" else "#efe2cf"
            elif new_style == "industrial":
                obj["color"] = "#6b6f76"
            elif new_style == "scandinavian":
                obj["color"] = "#d9d2c3"
        return updated_graph

    client = _get_client()

    instruction = (
        f"Current design graph:\n{json.dumps(current_graph, indent=2)}\n\n"
        f"Switch the theme/style to: {new_style}\n"
    )
    if preserve_layout:
        instruction += (
            "IMPORTANT: Preserve the room layout and furniture positions. "
            "Only change materials, colors, textures, and decorative elements "
            "to match the new style."
        )
    else:
        instruction += "You may adjust layout and furniture to better fit the new style."

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an architecture design AI specializing in style transformations. "
                    "You receive a full design graph and a new style. Return the complete "
                    "updated design graph JSON with the new style applied."
                ),
            },
            {"role": "user", "content": instruction},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": DESIGN_GRAPH_JSON_SCHEMA,
        },
        temperature=0.7,
        max_tokens=4096,
    )

    return json.loads(response.choices[0].message.content)


def _build_local_design_graph(
    prompt: str,
    room_type: str,
    style: str,
    project_id: str,
) -> DesignGraph:
    material_presets = {
        "modern": [
            {"id": "mat_floor_oak", "name": "Oak Flooring", "category": "wood", "color": "#9b6b3d"},
            {"id": "mat_wall_paint", "name": "Warm White Paint", "category": "paint", "color": "#f2eee8"},
            {"id": "mat_sofa_fabric", "name": "Soft Beige Fabric", "category": "fabric", "color": "#d9c7b0"},
            {"id": "mat_rug_wool", "name": "Sand Wool Rug", "category": "fabric", "color": "#d8ccb9"},
            {"id": "mat_metal_dark", "name": "Dark Bronze Metal", "category": "metal", "color": "#5f5245"},
        ],
        "spanish": [
            {"id": "mat_floor_terracotta", "name": "Terracotta Tile", "category": "tile", "color": "#b85e3b"},
            {"id": "mat_wall_plaster", "name": "Lime Plaster", "category": "plaster", "color": "#f1dfc9"},
            {"id": "mat_wood_oak", "name": "Dark Oak Wood", "category": "wood", "color": "#7b5232"},
            {"id": "mat_rug_wool", "name": "Patterned Wool Rug", "category": "fabric", "color": "#d8b59c"},
            {"id": "mat_metal_dark", "name": "Aged Iron", "category": "metal", "color": "#594a3f"},
        ],
    }
    materials = material_presets.get(style, material_presets["modern"])

    room_name = room_type.replace("_", " ").title()
    dims = {"length": 15, "width": 12, "height": 10}
    objects = [
        {
            "id": "sofa_1",
            "type": "sofa",
            "name": "Main Sofa",
            "position": {"x": 4.5, "y": 0, "z": 8.5},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 7, "width": 3, "height": 3},
            "material": materials[2]["id"],
            "color": materials[2]["color"],
        },
        {
            "id": "table_1",
            "type": "coffee_table",
            "name": "Coffee Table",
            "position": {"x": 4.5, "y": 0, "z": 5.8},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 3.5, "width": 2, "height": 1.4},
            "material": materials[0]["id"],
            "color": materials[0]["color"],
        },
        {
            "id": "chair_1",
            "type": "chair",
            "name": "Accent Chair",
            "position": {"x": 9.2, "y": 0, "z": 6.5},
            "rotation": {"x": 0, "y": -0.6, "z": 0},
            "dimensions": {"length": 2.5, "width": 2.5, "height": 3},
            "material": materials[2]["id"],
            "color": materials[2]["color"],
        },
        {
            "id": "rug_1",
            "type": "rug",
            "name": "Area Rug",
            "position": {"x": 4.8, "y": 0.02, "z": 6.7},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 7.5, "width": 5.5, "height": 0.05},
            "material": "mat_rug_wool",
            "color": materials[3]["color"],
        },
        {
            "id": "console_1",
            "type": "media_console",
            "name": "Media Console",
            "position": {"x": 4.5, "y": 0, "z": 1.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.3, "width": 5.5, "height": 2},
            "material": materials[0]["id"],
            "color": materials[0]["color"],
        },
        {
            "id": "lamp_1",
            "type": "floor_lamp",
            "name": "Floor Lamp",
            "position": {"x": 10.5, "y": 0, "z": 8.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.2, "width": 1.2, "height": 5.8},
            "material": "mat_metal_dark",
            "color": materials[4]["color"],
        },
        {
            "id": "plant_1",
            "type": "plant",
            "name": "Indoor Plant",
            "position": {"x": 12.2, "y": 0, "z": 2.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.4, "width": 1.4, "height": 4.2},
            "material": materials[4]["id"],
            "color": "#758b57",
        },
        {
            "id": "art_1",
            "type": "wall_art",
            "name": "Wall Art",
            "position": {"x": 4.6, "y": 5.6, "z": 0.16},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 0.1, "width": 3.8, "height": 2.1},
            "material": "mat_wall_paint",
            "color": "#d7b18f",
        },
    ]
    lighting = [
        {
            "id": "light_ambient_1",
            "type": "ambient",
            "position": {"x": 7.5, "y": 9.5, "z": 6},
            "intensity": 0.7,
            "color": "#fff4de",
        },
        {
            "id": "light_floor_1",
            "type": "point",
            "position": {"x": 10.5, "y": 5, "z": 8},
            "intensity": 0.4,
            "color": "#ffd7a8",
        },
    ]

    return _ai_response_to_design_graph(
        {
            "room": {"type": room_type, "dimensions": dims},
            "style": {
                "primary": style,
                "secondary": ["local-fallback", "starter-layout"],
                "color_palette": [material["color"] for material in materials],
                "materials": [material["name"] for material in materials],
            },
            "objects": objects,
            "materials": materials,
            "lighting": lighting,
            "render_prompt_2d": f"{style} {room_name} with warm, practical furniture based on prompt: {prompt}",
            "render_prompt_3d": f"{style} {room_name} 3D scene with realistic spacing and circulation.",
        },
        project_id=project_id,
    )


# ── Design Intake Orchestrator ───────────────────────────────────────────────

import asyncio
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.schemas import DesignStatus
from app.services import (
    concept_engine,
    drawing_engine,
    estimation_engine,
    layout_engine,
    render_engine,
    theme_engine,
)
from app.services.design_service import (
    PIPELINE_STAGE_NAMES,
    finalize_pipeline_run,
    get_design_by_id,
    initialize_pipeline_run,
    mark_design_failed,
    reset_stage_outputs,
    save_stage_output,
    update_design_status,
    update_stage_state,
)

STRUCTURED_RETRY_STAGES = {"render", "estimate"}
STAGE_NAME_ALIASES = {"estimation": "estimate"}


@dataclass(frozen=True)
class PipelineStage:
    name: str
    output_key: str
    runner: Callable[..., Any]
    requires: tuple[str, ...] = ()
    timeout_seconds: int = 30
    max_retries: int = 0
    retry_backoff_seconds: float = 1.0


@dataclass
class StageRunResult:
    payload: dict
    duration_seconds: float
    attempts: int
    retries_used: int


PIPELINE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage(name="theme", output_key="theme", runner=theme_engine.process, timeout_seconds=15),
    PipelineStage(
        name="concept",
        output_key="concept",
        runner=concept_engine.process,
        requires=("theme",),
        timeout_seconds=20,
    ),
    PipelineStage(
        name="layout",
        output_key="layout",
        runner=layout_engine.process,
        requires=("concept",),
        timeout_seconds=20,
    ),
    PipelineStage(
        name="drawing",
        output_key="drawing",
        runner=drawing_engine.process,
        requires=("layout",),
        timeout_seconds=15,
    ),
    PipelineStage(
        name="render",
        output_key="render",
        runner=render_engine.process,
        requires=("layout",),
        timeout_seconds=30,
        max_retries=2,
        retry_backoff_seconds=1.0,
    ),
    PipelineStage(
        name="estimate",
        output_key="estimate",
        runner=estimation_engine.process,
        requires=("layout",),
        timeout_seconds=20,
        max_retries=2,
        retry_backoff_seconds=1.0,
    ),
)

PIPELINE_INDEX = {stage.name: index for index, stage in enumerate(PIPELINE_ORDER)}
async def run_pipeline(
    design_id: str,
    *,
    start_stage: str | None = None,
    db: AsyncSession | None = None,
) -> dict:
    """
    Run the full design-intake pipeline, or resume from a later stage for future
    partial reruns such as layout-only edits.
    """
    manages_session = db is None
    if manages_session:
        async with async_session_factory() as session:
            try:
                result = await _run_pipeline_with_session(
                    session,
                    design_id,
                    start_stage=start_stage,
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    assert db is not None
    return await _run_pipeline_with_session(db, design_id, start_stage=start_stage)


async def _run_pipeline_with_session(
    db: AsyncSession,
    design_id: str,
    *,
    start_stage: str | None = None,
) -> dict:
    design = await get_design_by_id(db, design_id)
    if design is None:
        raise ValueError(f"Design {design_id} not found")

    normalized_start_stage = _normalize_stage_name(start_stage)
    stages_to_run = _resolve_stage_plan(normalized_start_stage)
    context = _build_pipeline_context(design)
    completed_upstream = _get_completed_upstream_stages(stages_to_run, context)

    _validate_stage_dependencies(stages_to_run, context)
    await reset_stage_outputs(db, design, [stage.name for stage in stages_to_run])
    await initialize_pipeline_run(
        db,
        design,
        stages_to_run=[stage.name for stage in stages_to_run],
        completed_stages=completed_upstream,
    )
    await update_design_status(db, design, DesignStatus.PROCESSING, error_message="")

    pipeline_started_at = _utcnow()
    _log_event(
        logging.INFO,
        "pipeline_started",
        design_id=design_id,
        start_stage=normalized_start_stage or PIPELINE_ORDER[0].name,
        stages=[stage.name for stage in stages_to_run],
    )

    try:
        for stage in stages_to_run:
            stage_result = await _run_stage(db, design, stage, context)
            context[stage.output_key] = stage_result.payload
            await save_stage_output(db, design, stage.name, stage_result.payload)
            await update_stage_state(
                db,
                design,
                stage_name=stage.name,
                status="completed",
                completed_at=_utcnow(),
                duration_seconds=stage_result.duration_seconds,
                attempt=stage_result.attempts,
                retries=stage_result.retries_used,
                error_message=None,
            )
            _log_event(
                logging.INFO,
                "stage_succeeded",
                design_id=design_id,
                stage=stage.name,
                duration_seconds=round(stage_result.duration_seconds, 4),
                attempts=stage_result.attempts,
            )

        pipeline_ended_at = _utcnow()
        await update_design_status(db, design, DesignStatus.COMPLETED, error_message="")
        await finalize_pipeline_run(
            db,
            design,
            end_time=pipeline_ended_at,
            total_duration_seconds=(pipeline_ended_at - pipeline_started_at).total_seconds(),
        )
        _log_event(
            logging.INFO,
            "pipeline_completed",
            design_id=design_id,
            total_duration_seconds=round((pipeline_ended_at - pipeline_started_at).total_seconds(), 4),
        )
        return {
            "design_id": design.id,
            "status": design.status,
            "pipeline_state": design.pipeline_state,
            "completed_stages": [stage.name for stage in stages_to_run],
            "outputs": {
                "theme": design.theme_config,
                "concept": design.concept_data,
                "layout": design.layout_data,
                "drawing": design.drawing_data,
                "render": design.render_data,
                "estimate": design.estimate_data,
            },
        }
    except Exception as exc:
        failed_stage = context.get("_active_stage", "unknown")
        stack_trace = traceback.format_exc()
        failed_at = _utcnow()
        await update_design_status(db, design, DesignStatus.FAILED, error_message=str(exc))
        await mark_design_failed(
            db,
            design,
            stage_name=failed_stage,
            error_message=str(exc),
            stack_trace=stack_trace,
        )
        await finalize_pipeline_run(
            db,
            design,
            end_time=failed_at,
            total_duration_seconds=(failed_at - pipeline_started_at).total_seconds(),
        )
        _log_event(
            logging.ERROR,
            "pipeline_failed",
            design_id=design_id,
            stage=failed_stage,
            error=str(exc),
        )
        raise


async def _run_stage(
    db: AsyncSession,
    design,
    stage: PipelineStage,
    context: dict,
) -> StageRunResult:
    started_at = _utcnow()
    retries_used = 0
    last_error: Exception | None = None

    for attempt in range(1, stage.max_retries + 2):
        context["_active_stage"] = stage.name
        await update_stage_state(
            db,
            design,
            stage_name=stage.name,
            status="processing",
            started_at=started_at,
            timeout_seconds=stage.timeout_seconds,
            attempt=attempt,
            retries=retries_used,
        )
        _log_event(
            logging.INFO,
            "stage_started",
            design_id=design.id,
            stage=stage.name,
            attempt=attempt,
            timeout_seconds=stage.timeout_seconds,
        )

        try:
            payload = await _execute_with_timeout(stage, context)
            finished_at = _utcnow()
            return StageRunResult(
                payload=payload,
                duration_seconds=(finished_at - started_at).total_seconds(),
                attempts=attempt,
                retries_used=retries_used,
            )
        except Exception as exc:
            last_error = exc
            retries_left = stage.max_retries - retries_used
            await update_stage_state(
                db,
                design,
                stage_name=stage.name,
                status="retrying" if retries_left > 0 else "failed",
                error_message=str(exc),
                attempt=attempt,
                retries=retries_used,
            )
            _log_event(
                logging.ERROR,
                "stage_failed",
                design_id=design.id,
                stage=stage.name,
                attempt=attempt,
                retries_left=max(retries_left, 0),
                error=str(exc),
            )
            if retries_left <= 0 or not _should_retry_stage(stage):
                break

            retries_used += 1
            backoff_seconds = _calculate_backoff(stage.retry_backoff_seconds, retries_used)
            _log_event(
                logging.WARNING,
                "stage_retrying",
                design_id=design.id,
                stage=stage.name,
                retry_attempt=retries_used,
                backoff_seconds=backoff_seconds,
            )
            await asyncio.sleep(backoff_seconds)

    assert last_error is not None
    raise last_error


async def _execute_with_timeout(stage: PipelineStage, context: dict) -> dict:
    args = _resolve_stage_args(stage, context)

    if asyncio.iscoroutinefunction(stage.runner):
        coroutine = stage.runner(*args)
    else:
        coroutine = asyncio.to_thread(stage.runner, *args)

    try:
        return await asyncio.wait_for(coroutine, timeout=stage.timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"Stage '{stage.name}' exceeded timeout after {stage.timeout_seconds} seconds"
        ) from exc


def _resolve_stage_args(stage: PipelineStage, context: dict) -> tuple:
    if stage.name == "theme":
        return (context["design_input"],)
    if stage.name == "concept":
        return (context["design_input"], context["theme"])
    if stage.name == "layout":
        return (context["design_input"], context["theme"], context["concept"])
    if stage.name == "drawing":
        return (context["design_input"], context["theme"], context["concept"], context["layout"])
    if stage.name in {"render", "estimate"}:
        return (context["layout"],)
    dependency_key = stage.requires[0]
    return (context[dependency_key],)


def _resolve_stage_plan(start_stage: str | None) -> tuple[PipelineStage, ...]:
    if start_stage is None:
        return PIPELINE_ORDER
    if start_stage not in PIPELINE_INDEX:
        supported = ", ".join(PIPELINE_INDEX)
        raise ValueError(f"Unsupported stage '{start_stage}'. Expected one of: {supported}")
    return PIPELINE_ORDER[PIPELINE_INDEX[start_stage] :]


def _build_pipeline_context(design) -> dict:
    return {
        "design_input": {
            "design_id": design.id,
            "room_type": design.room_type,
            "theme": design.theme,
            "dimensions": design.dimensions,
            "requirements": design.requirements,
            "budget": design.budget,
        },
        "theme": design.theme_config or {},
        "concept": design.concept_data or {},
        "layout": design.layout_data or {},
        "drawing": design.drawing_data or {},
        "render": design.render_data or {},
        "estimate": design.estimate_data or {},
    }


def _validate_stage_dependencies(stages_to_run: tuple[PipelineStage, ...], context: dict) -> None:
    planned_stage_names = {stage.name for stage in stages_to_run}
    for stage in stages_to_run:
        for dependency in stage.requires:
            if dependency in planned_stage_names:
                continue
            dependency_payload = context.get(dependency, {})
            if not dependency_payload:
                raise ValueError(
                    f"Cannot run stage '{stage.name}' because dependency '{dependency}' has no saved output"
                )


def _get_completed_upstream_stages(stages_to_run: tuple[PipelineStage, ...], context: dict) -> list[str]:
    planned_stage_names = {stage.name for stage in stages_to_run}
    return [
        stage_name
        for stage_name in PIPELINE_STAGE_NAMES
        if stage_name not in planned_stage_names and context.get(stage_name)
    ]


def _should_retry_stage(stage: PipelineStage) -> bool:
    return stage.name in STRUCTURED_RETRY_STAGES and stage.max_retries > 0


def _calculate_backoff(base_delay: float, retry_number: int) -> float:
    return base_delay * (2 ** (retry_number - 1))


def _normalize_stage_name(stage_name: str | None) -> str | None:
    if stage_name is None:
        return None
    normalized = stage_name.strip().lower()
    return STAGE_NAME_ALIASES.get(normalized, normalized)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log_event(level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, **fields})


def describe_pipeline_flow() -> list[dict]:
    """Helpful metadata for logs, tests, admin UIs, or Celery task introspection."""
    return [
        {
            "stage": stage.name,
            "requires": list(stage.requires),
            "persists_to": stage.output_key,
            "timeout_seconds": stage.timeout_seconds,
            "max_retries": stage.max_retries,
        }
        for stage in PIPELINE_ORDER
    ]
