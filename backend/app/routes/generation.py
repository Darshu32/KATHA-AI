"""Generation routes — initial design, local edit, theme switch, version history."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import (
    LocalEditRequest,
    PromptRequest,
    ThemeSwitchRequest,
)
from app.services.design_graph_service import (
    get_latest_render_for_version,
    get_latest_version,
    get_project,
    get_version,
    list_versions,
)
from app.services.object_bboxes import compute_object_bboxes
from app.services.storage import key_to_url
from app.services.generation_pipeline import (
    run_initial_generation,
    run_local_edit,
    run_theme_switch,
)
from app.services.diagrams import (
    generate_all as generate_all_diagrams,
    generate_one as generate_one_diagram,
    list_available as list_available_diagrams,
)
from app.services.exporters import available_formats, export as export_bundle
from app.services.knowledge_validator import validate_design_graph_async
from app.services.recommendations import recommend as build_recommendations
from app.services.recommendations_service import (
    RecommendationsError,
    RecommendationsRequest,
    generate_recommendations,
)
from app.knowledge import materials as _materials_kb
from app.services.pricing.knowledge_service import load_html_export_bands
from app.services.specs import build_spec_bundle
from app.services.standards.manufacturing_lookup import (
    lead_times_weeks_map as _lead_times_weeks_map_db,
)
from app.services.themes import get_theme as _get_theme_db

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post("/generate")
async def generate_design(
    project_id: str,
    payload: PromptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run full initial generation pipeline."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    project.status = "generating"
    await db.flush()

    result = await run_initial_generation(
        db=db,
        project_id=project_id,
        prompt=payload.prompt,
        room_type=payload.room_type,
        style=payload.style,
        camera=payload.camera,
        lighting=payload.lighting,
        view_mode=payload.view_mode,
        ratio=payload.ratio,
        quality=payload.quality,
        drawing_type=payload.drawing_type,
        project_type=project.project_type,
        region=project.region,
    )
    return result


@router.post("/edit")
async def local_edit(
    project_id: str,
    payload: LocalEditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a single object via prompt."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    result = await run_local_edit(
        db=db,
        project_id=project_id,
        object_id=payload.object_id,
        edit_prompt=payload.prompt,
        project_type=project.project_type,
        region=project.region,
    )
    return result


@router.post("/theme")
async def switch_theme_route(
    project_id: str,
    payload: ThemeSwitchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch the design theme."""
    project = await get_project(db, project_id)
    _check_owner(project, user)

    result = await run_theme_switch(
        db=db,
        project_id=project_id,
        new_style=payload.new_style,
        preserve_layout=payload.preserve_layout,
        project_type=project.project_type,
        region=project.region,
    )
    return result


@router.get("/versions")
async def list_versions_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    versions = await list_versions(db, project_id)
    return {
        "project_id": project_id,
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "change_type": v.change_type,
                "change_summary": v.change_summary,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ],
    }


@router.get("/versions/{version_num}")
async def get_version_route(
    project_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = await get_version(db, project_id, version_num)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    return {
        "id": version.id,
        "version": version.version,
        "change_type": version.change_type,
        "change_summary": version.change_summary,
        "graph_data": version.graph_data,
        "created_at": version.created_at.isoformat(),
    }


@router.get("/latest")
async def get_latest_route(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Latest version of a project — graph + render URL.

    Used by the project picker when re-opening an existing project so
    the gallery can render the most recent state without a re-generation.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")

    # Pull the most recent render asset for this version. Stored as a
    # short key; converted to the frontend-consumable URL here so the
    # caller doesn't need to know about the storage adapter.
    render = await get_latest_render_for_version(db, version.id)
    image_url = key_to_url(render.storage_key) if render and render.storage_key else None

    return {
        "id": version.id,
        "version": version.version,
        "graph_data": version.graph_data,
        "prompt": version.prompt,
        "image_url": image_url,
        "objects_bbox": compute_object_bboxes(version.graph_data),
    }


@router.post("/validate")
async def validate_route(
    project_id: str,
    version_num: int | None = None,
    segment: str = "residential",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run knowledge validator + recommendations on a stored graph version.

    If `version_num` is omitted, the latest version is used.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    report = await validate_design_graph_async(graph, segment=segment, session=db)
    style = (graph.get("style") or {}).get("primary") or ""
    theme_pack = await _get_theme_db(db, style) if style else None
    lt_map = await _lead_times_weeks_map_db(db)
    recommendations = build_recommendations(
        graph, theme_pack=theme_pack, lead_times_weeks=lt_map
    )
    return {
        "version": version.version,
        "validation": report,
        "recommendations": recommendations,
    }


# ── Second-speed advisor: LLM-authored recommendations ──────────────────────


def _dominant_material(graph: dict) -> tuple[str, str]:
    """Infer (primary_material, family) from the graph's materials + objects.

    Picks the most frequently named material across the materials list
    and object materials, then classifies it as ``wood`` / ``metal`` by
    matching against the knowledge-base catalogues (falls back to a
    keyword check for common species not keyed verbatim).
    """
    from collections import Counter

    names: list[str] = []
    for m in graph.get("materials", []) or []:
        n = (m.get("name") or "").strip()
        if n:
            names.append(n.lower())
    for o in graph.get("objects", []) or []:
        n = (o.get("material") or "").strip()
        if n:
            names.append(n.lower())
    if not names:
        return "", ""

    primary = Counter(names).most_common(1)[0][0]
    wood_keys = {k.lower() for k in _materials_kb.WOOD}
    metal_keys = {k.lower() for k in _materials_kb.METALS}

    family = ""
    if any(k in primary for k in wood_keys) or any(
        w in primary for w in
        ("wood", "walnut", "oak", "teak", "rosewood", "rubberwood", "pine", "plywood")
    ):
        family = "wood"
    elif any(k in primary for k in metal_keys) or any(
        w in primary for w in
        ("steel", "iron", "brass", "aluminium", "aluminum", "metal")
    ):
        family = "metal"

    return primary[:80], family[:32]


def _dominant_piece_type(graph: dict) -> str:
    """Most common object ``type`` in the graph (used as the piece type)."""
    from collections import Counter

    types = [
        (o.get("type") or "").strip().lower()
        for o in graph.get("objects", []) or []
    ]
    types = [t for t in types if t]
    if not types:
        return ""
    return Counter(types).most_common(1)[0][0][:80]


def _request_from_graph(graph: dict, project_name: str) -> RecommendationsRequest:
    """Build the LLM recommendations brief from a stored design graph."""
    style = ((graph.get("style") or {}).get("primary") or "")[:64]
    city = ((graph.get("site") or {}).get("location") or "").strip()[:80]
    primary_material, family = _dominant_material(graph)
    return RecommendationsRequest(
        project_name=(project_name or "KATHA Project")[:200],
        theme=style,
        piece_type=_dominant_piece_type(graph),
        primary_material=primary_material,
        primary_material_family=family,
        city=city,
    )


@router.post("/recommendations/full")
async def full_recommendations_route(
    project_id: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the LLM recommendations author against a stored graph version.

    This is the BRD §6 "second speed" advisor — slower than the
    deterministic ``/validate`` path (a live LLM call, ~3-8s) but it adds
    confidence / impact / effort labels and catalogue-grounded
    alternatives. The brief is derived from the version's graph (theme,
    dominant material + family, city, piece type) so the caller doesn't
    need to assemble it client-side.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    req = _request_from_graph(graph, project.name or "KATHA Project")
    try:
        report = await generate_recommendations(req, session=db)
    except RecommendationsError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return {"version": version.version, "report": report}


@router.get("/diagrams/available")
async def diagrams_available_route(
    project_id: str,
    user: User = Depends(get_current_user),
):
    """List diagram types supported by the platform."""
    return {"diagrams": list_available_diagrams()}


@router.post("/diagrams")
async def diagrams_route(
    project_id: str,
    version_num: int | None = None,
    diagram_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate auto-diagrams for a stored graph version.

    - If `diagram_id` is given, returns only that diagram.
    - Otherwise returns every ready diagram for the version.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    if diagram_id:
        single = generate_one_diagram(graph, diagram_id)
        if single is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown diagram '{diagram_id}'")
        return {"version": version.version, "diagrams": [single]}
    return {"version": version.version, "diagrams": generate_all_diagrams(graph)}


@router.get("/specs")
async def specs_route(
    project_id: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the structured spec bundle (material + manufacturing + MEP + cost)."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    bundle = build_spec_bundle(graph, project_name=project.name or "KATHA Project")
    return {"version": version.version, "spec_bundle": bundle}


@router.get("/export/formats")
async def export_formats_route(
    project_id: str,
    user: User = Depends(get_current_user),
):
    return {"formats": available_formats()}


@router.post("/export")
async def export_route(
    project_id: str,
    format: str,
    version_num: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the latest (or specified) version as pdf / docx / xlsx."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = (
        await get_version(db, project_id, version_num)
        if version_num is not None
        else await get_latest_version(db, project_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    graph = version.graph_data or {}
    brd_bands = await load_html_export_bands(db)
    bundle = build_spec_bundle(
        graph,
        project_name=project.name or "KATHA Project",
        brd_bands=brd_bands,
    )
    try:
        result = export_bundle(format, bundle, graph)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{result["filename"]}"'}
    return Response(content=result["bytes"], media_type=result["content_type"], headers=headers)
