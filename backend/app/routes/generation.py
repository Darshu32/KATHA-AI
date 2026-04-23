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
    get_latest_version,
    get_project,
    get_version,
    list_versions,
)
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
from app.services.knowledge_validator import validate_design_graph
from app.services.recommendations import recommend as build_recommendations
from app.services.specs import build_spec_bundle

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
    project = await get_project(db, project_id)
    _check_owner(project, user)

    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")

    return {
        "id": version.id,
        "version": version.version,
        "graph_data": version.graph_data,
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
    report = validate_design_graph(graph, segment=segment)
    recommendations = build_recommendations(graph)
    return {
        "version": version.version,
        "validation": report,
        "recommendations": recommendations,
    }


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
    bundle = build_spec_bundle(graph, project_name=project.name or "KATHA Project")
    try:
        result = export_bundle(format, bundle, graph)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{result["filename"]}"'}
    return Response(content=result["bytes"], media_type=result["content_type"], headers=headers)
