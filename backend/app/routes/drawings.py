"""Project drawing routes for floor-plan generation and retrieval."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.services.design_graph_service import get_latest_version, get_project, get_version
from app.services.project_drawing_service import generate_floor_plan_package

router = APIRouter(prefix="/projects/{project_id}/drawings", tags=["drawings"])


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/floor-plan")
async def get_floor_plan(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    target_version = (
        await get_version(db, project_id, version) if version is not None else await get_latest_version(db, project_id)
    )
    if target_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No design version found")

    drawing_payload = generate_floor_plan_package(target_version.graph_data)
    return {
        "project_id": project_id,
        "version": target_version.version,
        **drawing_payload,
    }
