"""Persistence helpers for design intake records and orchestration outputs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Design
from app.models.schemas import DesignRequest, DesignStatus

STAGE_OUTPUT_FIELDS = {
    "theme": "theme_config",
    "concept": "concept_data",
    "layout": "layout_data",
    "drawing": "drawing_data",
    "render": "render_data",
    "estimate": "estimate_data",
}

PIPELINE_STAGE_NAMES = tuple(STAGE_OUTPUT_FIELDS.keys())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().isoformat()


def build_pipeline_state(
    *,
    completed_stages: Iterable[str] = (),
    pending_stages: Iterable[str] | None = None,
) -> dict[str, str]:
    completed = set(completed_stages)
    pending = set(pending_stages or PIPELINE_STAGE_NAMES)
    state: dict[str, str] = {}
    for stage_name in PIPELINE_STAGE_NAMES:
        if stage_name in completed:
            state[stage_name] = "completed"
        elif stage_name in pending:
            state[stage_name] = "pending"
        else:
            state[stage_name] = "pending"
    return state


def _ensure_pipeline_metadata(design: Design) -> dict:
    metadata = dict(design.pipeline_metadata or {})
    metadata.setdefault("stage_history", [])
    metadata.setdefault(
        "stages",
        {
            stage_name: {
                "attempts": 0,
                "retries": 0,
                "duration_seconds": None,
                "last_error": None,
                "timeout_seconds": None,
            }
            for stage_name in PIPELINE_STAGE_NAMES
        },
    )
    return metadata


async def create_design(db: AsyncSession, payload: DesignRequest) -> Design:
    """
    Persist the normalized design intake request so the async generation pipeline
    can pick it up later and update status independently.
    """
    design = Design(
        room_type=payload.roomType,
        theme=payload.theme.value,
        dimensions=payload.dimensions.model_dump(),
        requirements=payload.requirements,
        budget=payload.budget,
        status=DesignStatus.ACCEPTED.value,
        pipeline_state=build_pipeline_state(),
        pipeline_metadata=_ensure_pipeline_metadata(Design()),
    )
    db.add(design)
    await db.flush()
    return design


async def get_design_by_id(db: AsyncSession, design_id: str) -> Design | None:
    result = await db.execute(select(Design).where(Design.id == design_id))
    return result.scalar_one_or_none()


async def update_design_status(
    db: AsyncSession,
    design: Design,
    status: DesignStatus,
    *,
    error_message: str | None = None,
) -> Design:
    design.status = status.value
    if error_message is not None:
        design.error_message = error_message
    await db.flush()
    return design


async def initialize_pipeline_run(
    db: AsyncSession,
    design: Design,
    *,
    stages_to_run: Iterable[str],
    completed_stages: Iterable[str],
) -> Design:
    metadata = _ensure_pipeline_metadata(design)
    metadata["start_time"] = _iso_now()
    metadata["end_time"] = None
    metadata["total_duration_seconds"] = None
    metadata["failed_stage"] = None
    metadata["stack_trace"] = None
    metadata["reset_stages"] = list(stages_to_run)
    metadata["last_completed_stage"] = None
    design.pipeline_metadata = metadata
    design.pipeline_state = build_pipeline_state(
        completed_stages=completed_stages,
        pending_stages=PIPELINE_STAGE_NAMES,
    )
    design.error_message = ""
    await db.flush()
    return design


async def update_stage_state(
    db: AsyncSession,
    design: Design,
    *,
    stage_name: str,
    status: str,
    timeout_seconds: int | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_seconds: float | None = None,
    attempt: int | None = None,
    retries: int | None = None,
) -> Design:
    pipeline_state = dict(design.pipeline_state or build_pipeline_state())
    pipeline_state[stage_name] = status
    design.pipeline_state = pipeline_state

    metadata = _ensure_pipeline_metadata(design)
    stage_metadata = dict(metadata["stages"].get(stage_name, {}))
    if timeout_seconds is not None:
        stage_metadata["timeout_seconds"] = timeout_seconds
    if started_at is not None:
        stage_metadata["started_at"] = started_at.isoformat()
    if completed_at is not None:
        stage_metadata["completed_at"] = completed_at.isoformat()
    if duration_seconds is not None:
        stage_metadata["duration_seconds"] = round(duration_seconds, 4)
    if attempt is not None:
        stage_metadata["attempts"] = attempt
    if retries is not None:
        stage_metadata["retries"] = retries
    if error_message is not None:
        stage_metadata["last_error"] = error_message
    elif status == "completed":
        stage_metadata["last_error"] = None
    stage_metadata["status"] = status
    metadata["stages"][stage_name] = stage_metadata
    design.pipeline_metadata = metadata

    await db.flush()
    return design


async def save_stage_output(
    db: AsyncSession,
    design: Design,
    stage_name: str,
    payload: dict,
) -> Design:
    field_name = STAGE_OUTPUT_FIELDS[stage_name]
    setattr(design, field_name, payload)

    metadata = _ensure_pipeline_metadata(design)
    stage_history = list(metadata.get("stage_history", []))
    stage_history.append(
        {
            "stage": stage_name,
            "saved_at": _iso_now(),
        }
    )
    metadata["stage_history"] = stage_history
    metadata["last_completed_stage"] = stage_name
    design.pipeline_metadata = metadata

    await db.flush()
    return design


async def finalize_pipeline_run(
    db: AsyncSession,
    design: Design,
    *,
    end_time: datetime,
    total_duration_seconds: float,
) -> Design:
    metadata = _ensure_pipeline_metadata(design)
    metadata["end_time"] = end_time.isoformat()
    metadata["total_duration_seconds"] = round(total_duration_seconds, 4)
    design.pipeline_metadata = metadata
    await db.flush()
    return design


async def mark_design_failed(
    db: AsyncSession,
    design: Design,
    *,
    stage_name: str,
    error_message: str,
    stack_trace: str | None = None,
) -> Design:
    design.status = DesignStatus.FAILED.value
    design.error_message = error_message

    pipeline_state = dict(design.pipeline_state or build_pipeline_state())
    if stage_name in pipeline_state:
        pipeline_state[stage_name] = "failed"
    design.pipeline_state = pipeline_state

    metadata = _ensure_pipeline_metadata(design)
    metadata["failed_stage"] = stage_name
    metadata["failed_at"] = _iso_now()
    metadata["stack_trace"] = stack_trace
    design.pipeline_metadata = metadata

    await db.flush()
    return design


async def reset_stage_outputs(
    db: AsyncSession,
    design: Design,
    stage_names: Iterable[str],
) -> Design:
    stage_names = list(stage_names)
    for stage_name in stage_names:
        field_name = STAGE_OUTPUT_FIELDS[stage_name]
        setattr(design, field_name, {})

    pipeline_state = dict(design.pipeline_state or build_pipeline_state())
    for stage_name in stage_names:
        pipeline_state[stage_name] = "pending"
    design.pipeline_state = pipeline_state

    metadata = _ensure_pipeline_metadata(design)
    metadata["reset_stages"] = stage_names
    for stage_name in stage_names:
        stage_metadata = dict(metadata["stages"].get(stage_name, {}))
        stage_metadata["status"] = "pending"
        stage_metadata["duration_seconds"] = None
        stage_metadata["started_at"] = None
        stage_metadata["completed_at"] = None
        stage_metadata["last_error"] = None
        metadata["stages"][stage_name] = stage_metadata
    design.pipeline_metadata = metadata

    await db.flush()
    return design
