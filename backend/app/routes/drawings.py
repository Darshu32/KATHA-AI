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
from app.services.project_drawing_service import generate_floor_plan_package
from app.services.elevation_view_drawing_service import (
    ElevationPiece,
    ElevationViewError,
    ElevationViewRequest,
    generate_elevation_view_drawing,
)
from app.services.section_view_drawing_service import (
    SectionViewError,
    SectionViewRequest,
    generate_section_view_drawing,
)
from app.services.isometric_view_drawing_service import (
    IsometricViewError,
    IsometricViewRequest,
    generate_isometric_view_drawing,
)
from app.services.detail_sheet_drawing_service import (
    DetailSheetError,
    DetailSheetRequest,
    generate_detail_sheet_drawing,
)

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


def _derive_piece(graph_data: dict) -> ElevationPiece:
    """Pick a representative furniture piece from the graph for furniture-scale views.

    The detail/section/isometric/elevation generators are furniture-scale; they
    fall back to ergonomic envelopes when only a piece *type* is supplied, so we
    hand them the primary object's type and let the service resolve dimensions.
    """
    objects = graph_data.get("objects") or []
    primary = objects[0] if objects and isinstance(objects[0], dict) else {}
    piece_type = str(primary.get("type") or primary.get("name") or "lounge_chair").strip().lower().replace(" ", "_")
    return ElevationPiece(type=piece_type or "lounge_chair")


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
    drawing_payload = generate_floor_plan_package(target_version.graph_data)
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
    graph = target_version.graph_data or {}
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
    target_version, theme, graph = await _generate_view(db, project_id, version, user)
    req = ElevationViewRequest(theme=theme, piece=_derive_piece(graph), design_graph=graph)
    try:
        result = await generate_elevation_view_drawing(req, session=db)
    except ElevationViewError as exc:
        _raise_drawing_error(exc)
    return _view_response(project_id, target_version.version, result)


@router.get("/section-view")
async def get_section_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, theme, graph = await _generate_view(db, project_id, version, user)
    req = SectionViewRequest(theme=theme, piece=_derive_piece(graph))
    try:
        result = await generate_section_view_drawing(req, session=db)
    except SectionViewError as exc:
        _raise_drawing_error(exc)
    return _view_response(project_id, target_version.version, result)


@router.get("/isometric-view")
async def get_isometric_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, theme, graph = await _generate_view(db, project_id, version, user)
    req = IsometricViewRequest(theme=theme, piece=_derive_piece(graph))
    try:
        result = await generate_isometric_view_drawing(req, session=db)
    except IsometricViewError as exc:
        _raise_drawing_error(exc)
    return _view_response(project_id, target_version.version, result)


@router.get("/detail-sheet")
async def get_detail_sheet(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, theme, graph = await _generate_view(db, project_id, version, user)
    req = DetailSheetRequest(theme=theme, piece=_derive_piece(graph))
    try:
        result = await generate_detail_sheet_drawing(req, session=db)
    except DetailSheetError as exc:
        _raise_drawing_error(exc)
    return _view_response(project_id, target_version.version, result)
