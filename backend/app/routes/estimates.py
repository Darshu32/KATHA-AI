"""Estimate routes — compute and retrieve material/cost estimates."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.services.design_graph_service import get_latest_version, get_project, get_version
from app.services.estimation_engine import compute_estimate

router = APIRouter(prefix="/projects/{project_id}/estimates", tags=["estimates"])


@router.get("")
async def get_estimate_for_latest(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute estimate for the latest design version."""
    project = await get_project(db, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No design versions")

    estimate = compute_estimate(version.graph_data)
    return {
        "project_id": project_id,
        "version": version.version,
        **estimate,
    }


@router.get("/version/{version_num}")
async def get_estimate_for_version(
    project_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute estimate for a specific design version."""
    project = await get_project(db, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    version = await get_version(db, project_id, version_num)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    estimate = compute_estimate(version.graph_data)
    return {
        "project_id": project_id,
        "version": version_num,
        **estimate,
    }
