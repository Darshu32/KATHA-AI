"""Project drawing routes for floor-plan generation and retrieval."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.knowledge import themes
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.services.design_graph_service import get_latest_version, get_project, get_version
from app.services.graph_normalizer import normalize_graph
from app.services.project_drawing_service import generate_floor_plan_package
from app.services.architectural_views_service import (
    generate_detail_package,
    generate_elevation_package,
    generate_isometric_package,
    generate_section_package,
)
from app.services.view_fidelity import verify_graph_views

router = APIRouter(prefix="/projects/{project_id}/drawings", tags=["drawings"])


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


async def _resolve_target_version(db: AsyncSession, project_id: str, version: int | None):
    target_version = (
        await get_version(db, project_id, version) if version is not None else await get_latest_version(db, project_id)
    )
    if target_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No design version found")
    return target_version


def _resolve_theme(graph_data: dict) -> str:
    """Map the saved graph style onto a known theme rule pack (fallback: modern)."""
    style = graph_data.get("style") or {}
    candidate = str(style.get("primary") or "").strip()
    if candidate and themes.get(candidate):
        return candidate
    return "modern"


def _raise_drawing_error(exc: Exception) -> None:
    msg = str(exc)
    if "Unknown theme" in msg:
        code = status.HTTP_400_BAD_REQUEST
        err = "invalid_theme"
    else:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
        err = "llm_unavailable"
    raise HTTPException(
        status_code=code,
        detail=ErrorResponse(error=err, message=msg).model_dump(),
    ) from exc


@router.get("/floor-plan")
async def get_floor_plan(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project(db, project_id)
    _check_owner(project, user)

    target_version = await _resolve_target_version(db, project_id, version)
    # Defensive read-time normalization: versions saved before the normalization
    # layer (or any future schema drift) are corrected on the fly. Idempotent,
    # so already-clean graphs pass through unchanged.
    clean_graph, _ = normalize_graph(target_version.graph_data or {})
    drawing_payload = generate_floor_plan_package(clean_graph)
    return {
        "project_id": project_id,
        "version": target_version.version,
        **drawing_payload,
    }


async def _generate_view(
    db: AsyncSession,
    project_id: str,
    version: int | None,
    user: User,
) -> tuple[Any, str, dict]:
    """Shared setup for furniture-scale views — returns (version_row, theme, graph)."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    target_version = await _resolve_target_version(db, project_id, version)
    # Defensive read-time normalization (idempotent) so pre-normalization
    # versions render with correct axes / units / bounds.
    graph, _ = normalize_graph(target_version.graph_data or {})
    return target_version, _resolve_theme(graph), graph


def _view_response(project_id: str, version_num: int, result: dict) -> dict:
    """Normalise generator output so the frontend always reads `preview_svg`."""
    return {
        "project_id": project_id,
        "version": version_num,
        "preview_svg": result.get("svg") or result.get("preview_svg"),
        **result,
    }


@router.get("/elevation-view")
async def get_elevation_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    result = generate_elevation_package(graph)
    return _view_response(project_id, target_version.version, result)


@router.get("/section-view")
async def get_section_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    result = generate_section_package(graph)
    return _view_response(project_id, target_version.version, result)


@router.get("/isometric-view")
async def get_isometric_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    result = generate_isometric_package(graph)
    return _view_response(project_id, target_version.version, result)


@router.get("/detail-sheet")
async def get_detail_sheet(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    result = generate_detail_package(graph)
    return _view_response(project_id, target_version.version, result)


@router.get("/fidelity")
async def get_view_fidelity(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prove the views faithfully depict the design (no architectural judgement).

    Cross-checks each rendered view against the design graph: every object the
    user designed appears in every relevant view, and every dimension annotated
    on a drawing equals the graph's room envelope. Returns a machine-readable
    report the UI can surface as a "verified faithful to your design" badge.
    """
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    report = verify_graph_views(graph)
    return {
        "project_id": project_id,
        "version": target_version.version,
        **report,
    }
