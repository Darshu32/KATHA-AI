"""Generation routes — initial design, local edit, theme switch, version history."""

from fastapi import APIRouter, Depends, HTTPException, status
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
