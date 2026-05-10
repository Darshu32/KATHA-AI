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
    save_render_asset,
)
from app.services.estimation_engine import compute_estimate
from app.services.graph_describer import describe_graph_for_render
from app.services.image_service import generate_image

logger = logging.getLogger(__name__)


async def _attach_render(
    db: AsyncSession,
    *,
    graph_version_id: str,
    prompt: str,
    project_type: str | None,
    theme: str | None,
    graph_data: dict | None = None,
    theme_label: str | None = None,
) -> str | None:
    """Best-effort: render an image for the just-saved version and persist
    it as a GeneratedAsset of type 'render_2d'. Returns the storage_key
    (data URI) on success or None when the provider is unconfigured /
    failed. Never raises — graph is already saved at this point.

    When ``graph_data`` is supplied, we append a structured description
    of the graph (objects, materials, dimensions, positions) to the
    prompt so the image model is conditioned on the actual geometry,
    not just the user's brief. This is the structured-text path of
    graph-driven rendering — the load-bearing step that lets edits
    like "move the table 30cm right" surface in the next render.
    """
    if not prompt or not prompt.strip():
        return None
    enriched_prompt = prompt.strip()
    if graph_data is not None:
        graph_desc = describe_graph_for_render(graph_data)
        if graph_desc:
            enriched_prompt = f"{enriched_prompt}\n\n{graph_desc}"
    try:
        result = await generate_image(
            enriched_prompt,
            project_type=project_type,
            theme=theme,
            theme_label=theme_label,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Render generation failed for version %s: %s",
                       graph_version_id, exc)
        return None
    if not result or not result.get("url"):
        return None
    storage_key = result["url"]
    try:
        await save_render_asset(
            db,
            graph_version_id=graph_version_id,
            storage_key=storage_key,
            mime_type=str(result.get("mime_type") or "image/png"),
            metadata={
                "source": result.get("source", "gemini"),
                "title": result.get("title", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Persisting render asset failed for version %s: %s",
                       graph_version_id, exc)
        # Asset row didn't save, but the URL itself is still useful to
        # the caller — return it so the response can carry the render.
    return storage_key


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
    project_type: str | None = None,
) -> dict:
    """
    Full pipeline for initial design:
    1. AI generates structured design graph
    2. Save as version 1
    3. Compute estimate
    4. Render a 2D image, persist as GeneratedAsset (best-effort)
    5. Return combined result
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

    # Step 2 — Persist (capture prompt so re-renders inherit context)
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=graph_data,
        change_type="initial",
        change_summary=f"Initial generation from prompt: {prompt[:100]}",
        prompt=prompt,
    )

    # Step 3 — Estimate
    estimate = compute_estimate(graph_data)

    # Step 4 — Render (best-effort; doesn't fail the response if Gemini
    # is down or the API key is unset). The graph_data flows in so the
    # image model is conditioned on the actual generated geometry, not
    # just the user's typed brief.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=prompt,
        project_type=project_type,
        theme=style,
        graph_data=graph_data,
    )

    logger.info(
        "Generation complete: project=%s version=%d objects=%d render=%s",
        project_id,
        version.version,
        len(graph_data.get("objects", [])),
        "yes" if image_url else "no",
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": graph_data,
        "estimate": estimate,
        "image_url": image_url,
        "status": "completed",
    }


async def run_local_edit(
    db: AsyncSession,
    project_id: str,
    object_id: str,
    edit_prompt: str,
    project_type: str | None = None,
) -> dict:
    """
    Edit a single object:
    1. Load latest version
    2. AI edits the target object
    3. Save new version (preserves the originating prompt)
    4. Recompute estimate
    5. Re-render — combines original prompt + edit hint for context
    """

    latest = await get_latest_version(db, project_id)
    if latest is None:
        raise ValueError(f"No versions found for project {project_id}")

    current_graph = latest.graph_data
    base_prompt = (latest.prompt or "").strip()
    # Render context: original prompt + the edit hint, so Gemini has
    # the design's framing instead of just "make it walnut".
    render_prompt = (
        f"{base_prompt} — {edit_prompt.strip()}"
        if base_prompt
        else edit_prompt.strip()
    )
    theme = (current_graph.get("style") or {}).get("name") if isinstance(current_graph, dict) else None

    # AI edit
    updated_graph = await edit_object_via_prompt(
        current_graph=current_graph,
        object_id=object_id,
        edit_prompt=edit_prompt,
    )

    # Persist (preserve the originating prompt across the edit chain)
    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph,
        change_type="prompt_edit",
        change_summary=f"Edited {object_id}: {edit_prompt[:100]}",
        changed_object_ids=[object_id],
        parent_version_id=latest.id,
        prompt=base_prompt or None,
    )

    estimate = compute_estimate(updated_graph)

    # Render against the *updated* graph so geometric edits surface
    # in the new render rather than just the data layer.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=render_prompt,
        project_type=project_type,
        theme=theme,
        graph_data=updated_graph,
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph,
        "estimate": estimate,
        "changed_objects": [object_id],
        "image_url": image_url,
        "status": "completed",
    }


async def run_theme_switch(
    db: AsyncSession,
    project_id: str,
    new_style: str,
    preserve_layout: bool = True,
    project_type: str | None = None,
) -> dict:
    """
    Switch the entire design theme:
    1. Load latest version
    2. AI applies new theme
    3. Save new version (preserves the originating prompt)
    4. Recompute estimate
    5. Re-render — same originating prompt with the new theme hint
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

    base_prompt = (latest.prompt or "").strip() or None

    version = await save_graph_version(
        db=db,
        project_id=project_id,
        graph_data=updated_graph_data,
        change_type="theme_switch",
        change_summary=f"Theme switched to {new_style}",
        parent_version_id=latest.id,
        prompt=base_prompt,
    )

    estimate = compute_estimate(updated_graph_data)

    # Theme switch keeps the same geometry — pass the updated graph so
    # the new render is conditioned on layout that's literally
    # unchanged, with only material / palette differing per the new
    # theme hint.
    image_url = await _attach_render(
        db,
        graph_version_id=version.id,
        prompt=base_prompt or new_style,
        project_type=project_type,
        theme=new_style,
        graph_data=updated_graph_data,
    )

    return {
        "project_id": project_id,
        "version": version.version,
        "version_id": version.id,
        "graph_data": updated_graph_data,
        "estimate": estimate,
        "image_url": image_url,
        "status": "completed",
    }


def _normalize_ai_output(ai_output: dict, previous: dict) -> dict:
    """Ensure AI output retains our internal structure fields."""
    # Carry forward fields that AI might not return
    for key in ("project_id", "version", "design_type", "site", "constraints"):
        if key not in ai_output and key in previous:
            ai_output[key] = previous[key]
    return ai_output
