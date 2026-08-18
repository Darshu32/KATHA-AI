"""Project drawing routes for floor-plan generation and retrieval."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
# Piece-scale (furniture/product) renderers — deterministic; used when the
# workspace scope selector is set to furniture/product instead of room-scale.
from app.services.drawings.plan_view import render_plan_view
from app.services.drawings.elevation_view import render_elevation_view
from app.services.drawings.section_view import render_section_view
from app.services.drawings.isometric_view import render_isometric_view
from app.services.drawings.detail_sheet import render_detail_sheet
from app.services.view_fidelity import verify_graph_views
# Geometry-true drawings — cut/projected from the real Manifold kernel solids.
from app.services.spatial.drawings2d import (
    elevation_svg as _geo_elevation,
    plan_svg as _geo_plan,
    section_svg as _geo_section,
    sheet_dxf,
    sheet_pdf,
    sheet_svg,
)

router = APIRouter(prefix="/projects/{project_id}/drawings", tags=["drawings"])

_GEO_VIEWS = {"plan": _geo_plan, "section": _geo_section, "elevation": _geo_elevation}

# Scopes that mean "draw the furniture piece" rather than the room.
PIECE_SCOPES = {"furniture", "product"}


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _to_mm(value) -> float:
    """Coerce a graph dimension (metres or mm) to millimetres."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v * 1000.0 if 0 < v <= 20 else v


def _piece_from_graph(graph: dict) -> dict:
    """Derive a single furniture-piece envelope from the design graph — the
    dominant object by volume, with ergonomic targets estimated from its height
    so the piece-scale renderers draw a real silhouette / profile."""
    objs = graph.get("objects") or []
    if not objs:
        return {"type": "piece", "dimensions_mm": {"length": 800, "width": 800, "height": 750}}

    def _vol(o):
        d = o.get("dimensions") or {}
        return _to_mm(d.get("length")) * _to_mm(d.get("width")) * max(_to_mm(d.get("height")), 1.0)

    obj = max(objs, key=_vol)
    d = obj.get("dimensions") or {}
    length = _to_mm(d.get("length")) or 800
    width = _to_mm(d.get("width")) or 800
    height = _to_mm(d.get("height")) or 750
    mat = (obj.get("material") or "").lower()
    hatch = None
    if any(w in mat for w in ("wood", "oak", "walnut", "teak", "ply")):
        hatch = "wood"
    elif any(w in mat for w in ("steel", "metal", "brass", "iron", "alumin")):
        hatch = "metal"
    return {
        "type": obj.get("type") or "piece",
        "dimensions_mm": {"length": length, "width": width, "height": height},
        "ergonomic_targets_mm": {
            "seat_height_mm": round(height * 0.42),
            "back_height_mm": round(height * 0.96),
            "arm_height_mm": round(height * 0.62),
            "seat_depth_mm": round(width * 0.62),
        },
        "material_hatch_key": hatch,
        "leg_base_hatch_key": "metal" if hatch == "wood" else None,
    }


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
    scope: str = Query(default="interior"),
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

    if scope.lower() in PIECE_SCOPES:
        # Furniture plan = top-down footprint of the piece, framed with margin.
        piece = _piece_from_graph(clean_graph)
        dm = piece["dimensions_mm"]
        length_m, width_m = dm["length"] / 1000.0, dm["width"] / 1000.0
        m = 1.3
        piece_graph = {
            "room": {"dimensions": {"length": length_m * m, "width": width_m * m}},
            "objects": [{
                "type": piece["type"],
                "dimensions": {"length": length_m, "width": width_m},
                "position": {"x": length_m * m / 2, "z": width_m * m / 2},
            }],
        }
        result = render_plan_view(graph=piece_graph)
        return _view_response(project_id, target_version.version, result)

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
    scope: str = Query(default="interior"),
    face: str | None = Query(default=None, description="north|south|east|west; default = longest side"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    if scope.lower() in PIECE_SCOPES:
        result = render_elevation_view(piece=_piece_from_graph(graph))
    else:
        result = generate_elevation_package(graph, face=face)
    return _view_response(project_id, target_version.version, result)


@router.get("/section-view")
async def get_section_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    scope: str = Query(default="interior"),
    cut_axis: str | None = Query(default=None, description="x|z; default cuts ⊥ z"),
    cut_at: float | None = Query(default=None, description="cut position in metres; default passes through the most rooms"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    if scope.lower() in PIECE_SCOPES:
        result = render_section_view(piece=_piece_from_graph(graph))
    else:
        result = generate_section_package(graph, cut_axis=cut_axis, cut_at=cut_at)
    return _view_response(project_id, target_version.version, result)


@router.get("/isometric-view")
async def get_isometric_view(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    scope: str = Query(default="interior"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    if scope.lower() in PIECE_SCOPES:
        result = render_isometric_view(piece=_piece_from_graph(graph))
    else:
        result = generate_isometric_package(graph)
    return _view_response(project_id, target_version.version, result)


@router.get("/detail-sheet")
async def get_detail_sheet(
    project_id: str,
    version: int | None = Query(default=None, ge=1),
    scope: str = Query(default="interior"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_version, _theme, graph = await _generate_view(db, project_id, version, user)
    if scope.lower() in PIECE_SCOPES and str(graph.get("design_type") or "").lower() != "product":
        # Piece detail cells are LLM-authored (the /working-drawings path);
        # the deterministic sheet renders its frame + a "needs authoring" note.
        result = render_detail_sheet()
    else:
        # A product's component-joinery sheet is rendered deterministically by
        # generate_detail_package (its design_type branch), so route products
        # there even under a piece scope — no "needs authoring" placeholder.
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


@router.get("/sheet")
async def geometry_sheet(
    project_id: str,
    format: str = Query("svg", pattern="^(svg|pdf|dxf)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Geometry-true general-arrangement sheet (plan + section + elevation),
    cut and projected from the real 3D kernel solids. format = svg | pdf | dxf."""
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")
    graph = version.graph_data or {}
    meta = {"project_name": project.name, "scale": "NTS", "sheet": "A-101", "region": project.region}
    try:
        if format == "pdf":
            data, media = sheet_pdf(graph, meta), "application/pdf"
        elif format == "dxf":
            data, media = sheet_dxf(graph), "image/vnd.dxf"
        else:
            data, media = sheet_svg(graph, meta).encode("utf-8"), "image/svg+xml"
    except Exception as exc:  # noqa: BLE001 — drawings must never 500 the app hard
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Sheet generation failed") from exc
    headers = {"Cache-Control": "no-store"}
    if format in ("pdf", "dxf"):
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (project.name or "sheet"))
        headers["Content-Disposition"] = f'attachment; filename="{safe}.{format}"'
    return Response(content=data, media_type=media, headers=headers)


@router.get("/geometry/{view}")
async def geometry_view(
    project_id: str,
    view: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A single geometry-true view SVG (view = plan | section | elevation)."""
    fn = _GEO_VIEWS.get(view)
    if fn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown view")
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")
    try:
        svg = fn(version.graph_data or {})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Drawing generation failed") from exc
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
