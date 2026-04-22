"""Generation Pipeline — orchestrates the full flow from prompt to design graph + assets."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_orchestrator import (
    edit_object_via_prompt,
    generate_design_graph,
    switch_theme,
)
from app.services.design_graph_service import (
    get_latest_version,
    save_graph_version,
)
from app.services.estimation_engine import compute_estimate

logger = logging.getLogger(__name__)


async def run_initial_generation(
    db: AsyncSession,
    project_id: str,
    prompt: str,
    room_type: str = "living_room",
    style: str = "modern",
    camera: str | None = None,
    lighting: str | None = None,
    view_mode: str | None = None,
    ratio: str | None = None,
    quality: str | None = None,
    drawing_type: str | None = None,
) -> dict:
    """
    Full pipeline for initial design:
    1. AI generates structured design graph
    2. Save as version 1
    3. Compute estimate
    4. Return combined result
    """

    # Step 1 — AI generation
    logger.info("Starting initial generation for project %s", project_id)
    design_graph = await generate_design_graph(
        prompt=prompt,
        room_type=room_type,
        style=style,
        project_id=project_id,
        camera=camera,
        lighting=lighting,
        view_mode=view_mode,
        ratio=ratio,
        quality=quality,
        drawing_type=drawing_type,
    )
    graph_data = design_graph.model_dump()

    # Step 2 — Persist
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=graph_data,
        change_type="initial",
        change_summary=f"Initial generation from prompt: {prompt[:100]}",
    )

    # Step 3 — Estimate
    estimate = compute_estimate(graph_data)

    logger.info(
        "Generation complete: project=%s version=%d objects=%d",
        project_id,
        version.version,
        len(graph_data.get("objects", [])),
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": graph_data,
        "estimate": estimate,
        "status": "completed",
    }


async def run_local_edit(
    db: AsyncSession,
    project_id: str,
    object_id: str,
    edit_prompt: str,
) -> dict:
    """
    Edit a single object:
    1. Load latest version
    2. AI edits the target object
    3. Save new version
    4. Recompute estimate
    """

    latest = await get_latest_version(db, project_id)
    if latest is None:
        raise ValueError(f"No versions found for project {project_id}")

    current_graph = latest.graph_data

    # AI edit
    updated_graph = await edit_object_via_prompt(
        current_graph=current_graph,
        object_id=object_id,
        edit_prompt=edit_prompt,
    )

    # Persist
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph,
        change_type="prompt_edit",
        change_summary=f"Edited {object_id}: {edit_prompt[:100]}",
        changed_object_ids=[object_id],
        parent_version_id=latest.id,
    )

    estimate = compute_estimate(updated_graph)

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph,
        "estimate": estimate,
        "changed_objects": [object_id],
        "status": "completed",
    }


async def run_theme_switch(
    db: AsyncSession,
    project_id: str,
    new_style: str,
    preserve_layout: bool = True,
) -> dict:
    """
    Switch the entire design theme:
    1. Load latest version
    2. AI applies new theme
    3. Save new version
    4. Recompute estimate
    """

    latest = await get_latest_version(db, project_id)
    if latest is None:
        raise ValueError(f"No versions found for project {project_id}")

    updated_graph = await switch_theme(
        current_graph=latest.graph_data,
        new_style=new_style,
        preserve_layout=preserve_layout,
    )

    # Re-wrap as internal design graph format
    updated_graph_data = _normalize_ai_output(updated_graph, latest.graph_data)

    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph_data,
        change_type="theme_switch",
        change_summary=f"Theme switched to {new_style}",
        parent_version_id=latest.id,
    )

    estimate = compute_estimate(updated_graph_data)

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph_data,
        "estimate": estimate,
        "status": "completed",
    }


def _normalize_ai_output(ai_output: dict, previous: dict) -> dict:
    """Ensure AI output retains our internal structure fields."""
    # Carry forward fields that AI might not return
    for key in ("project_id", "version", "design_type", "site", "constraints"):
        if key not in ai_output and key in previous:
            ai_output[key] = previous[key]
    return ai_output
