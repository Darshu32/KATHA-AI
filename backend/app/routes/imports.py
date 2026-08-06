"""Import routes (BRD Layer 5B).

Two stages:
    POST /imports/parse        — multipart upload; deterministic parser
                                 returns the structured payload per file.
    POST /imports/advisor      — LLM ingestion manifest over a list of
                                 already-parsed payloads.
    POST /imports/advisor/knowledge — preview the knowledge slice the
                                 LLM stage will see.
    GET  /imports/formats      — list supported extensions.
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.services.import_advisor_service import (
    ImportAdvisorError,
    ImportAdvisorRequest,
    build_import_advisor_knowledge,
    generate_import_manifest,
)
from app.services.importers import parse as parse_file
from app.services.importers import supported_extensions
from app.services.floorplan_import import floorplan_to_design
from app.services.importers.mesh_geometry import load_mesh, supported_mesh_extensions
from app.services.mesh_reconstruct import reconstruct_from_mesh
from app.services.spatial.drawings2d import mesh_spec_sheet_svg, sheet_svg, spec_sheet_svg
from app.services.spatial.render_pipeline import render_design, render_mesh, render_parts
from app.services.themes import get_theme as _get_theme_db
from app.vision.base import VisionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/formats")
async def list_import_formats() -> dict:
    """Supported file extensions for the deterministic parsers."""
    return {"extensions": supported_extensions()}


@router.post("/parse")
async def parse_uploads(files: list[UploadFile] = File(...)) -> dict:
    """Run the deterministic importers on each uploaded file."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="no_files",
                                 message="At least one file is required.").model_dump(),
        )
    results: list[dict] = []
    for f in files:
        body = await f.read()
        try:
            results.append(parse_file(f.filename or "upload", body))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Importer failed for %s", f.filename)
            results.append({
                "format": "error",
                "filename": f.filename or "upload",
                "size_bytes": len(body),
                "summary": "Parser threw an exception.",
                "extracted": {},
                "warnings": [f"parser_error: {exc}"],
            })
    return {"count": len(results), "imports": results}


@router.get("/3d/formats")
async def list_3d_formats() -> dict:
    """3D-model formats accepted by the geometry import → render path (Layer 5B)."""
    return {"extensions": sorted(supported_mesh_extensions())}


@router.post("/3d/render")
async def render_3d_model(
    file: UploadFile = File(..., description="3D model: OBJ / GLB / glTF / STL / PLY / OFF"),
    style: str = Form(
        default="",
        description="Optional material/finish hint, e.g. 'walnut and tan leather'. An uploaded "
                    "mesh carries no materials, so this guides the photoreal finish.",
    ),
    user: User = Depends(get_current_user),
) -> dict:
    """Upload a 3D model → photoreal render + overall dimensions (Layer 5B, Tier 1
    of upload→geometry). The mesh is framed by the real kernel camera + rasteriser
    and finished by Nano Banana; no editable spec is reconstructed yet (Tier 2)."""
    body = await file.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="empty_file", message="The uploaded file is empty.").model_dump())
    try:
        mesh = load_mesh(file.filename or "model", body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_model", message=str(exc)).model_dump())

    result = await render_mesh(mesh["verts"], mesh["tris"], style=(style.strip() or None))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(error="unrenderable",
                                 message="The model produced no renderable geometry.").model_dump())

    # Spec sheet — the fuller deliverable: front/side/top silhouettes + dims +
    # model stats (upload analog of the product spec sheet). Best-effort.
    sheet_meta = {
        "filename": file.filename, "units_known": mesh["units_known"],
        "n_tris": mesh["n_tris"], "n_verts": mesh["n_verts"],
        "watertight": mesh["watertight"], "volume": mesh["volume"], "area": mesh["area"],
    }
    spec_sheet = None
    try:
        svg = mesh_spec_sheet_svg(mesh["verts"], mesh["tris"], sheet_meta)
        spec_sheet = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    except Exception as exc:  # noqa: BLE001 — the render already succeeded
        logger.warning("mesh spec sheet failed for %s: %s", file.filename, exc)

    length, height, depth = mesh["dims"]
    return {
        "filename": file.filename,
        "render": {
            "image": f"data:{result.mime};base64,{base64.b64encode(result.image_bytes).decode()}",
            "provider": result.provider,
            "finished": result.finished,
            "kind": result.kind,
        },
        "spec_sheet": spec_sheet,
        "dimensions_m": {"length": round(length, 3), "height": round(height, 3), "depth": round(depth, 3)},
        "units_known": mesh["units_known"],
        "mesh": {"vertices": mesh["n_verts"], "triangles": mesh["n_tris"],
                 "watertight": mesh["watertight"], "up_axis_flipped": mesh["up_axis_flipped"]},
        "hotspots": result.hotspots,
    }


@router.post("/floorplan/render")
async def render_floorplan(
    file: UploadFile = File(..., description="Floor-plan image (PNG / JPG / WEBP)"),
    style: str = Form(
        default="",
        description="Optional style/theme for the reconstruction, e.g. 'modern', 'scandinavian'.",
    ),
    user: User = Depends(get_current_user),
) -> dict:
    """Upload a floor-plan image → a vision LLM reads its ROOM PROGRAM (rooms +
    areas + adjacencies), which flows into the multi-room layout solver + kernel:
    a modelled, furnished, dimensioned multi-room design + GA sheet. Spec-first
    reconstruction (the program is recovered and re-laid-out), not a pixel trace."""
    body = await file.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="empty_file", message="The uploaded file is empty.").model_dump())
    mime = (file.content_type or "image/png").lower()
    if not mime.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="not_image",
                                 message="Upload a floor-plan IMAGE (PNG/JPG/WEBP).").model_dump())
    try:
        graph, program, solution = await floorplan_to_design(
            body, mime, "floorplan_import", (style.strip() or None))
    except VisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(error="vision_failed",
                                 message=f"Couldn't read the floor plan: {exc}").model_dump())

    render_payload = None
    result = await render_design(graph)
    if result and result.image_bytes:
        render_payload = {
            "image": f"data:{result.mime};base64,{base64.b64encode(result.image_bytes).decode()}",
            "provider": result.provider, "finished": result.finished, "kind": result.kind,
        }
    plan_sheet = None
    try:
        svg = sheet_svg(graph, {"project_name": file.filename or "Imported plan"})
        plan_sheet = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    except Exception as exc:  # noqa: BLE001 — the render already succeeded
        logger.warning("floorplan plan sheet failed: %s", exc)

    rooms = [r for r in (program.get("rooms") or []) if isinstance(r, dict)]
    return {
        "filename": file.filename,
        "program": {
            "rooms": rooms,
            "adjacencies": program.get("adjacencies") or [],
            "notes": program.get("notes"),
        },
        "render": render_payload,
        "plan_sheet": plan_sheet,
        "graph": graph,                 # solved multi-room graph — editable ("open as project")
        "solved": solution is not None,
        "room_count": len(rooms),
        "total_area_sqm": round(sum(float(r.get("area_sqm") or 0) for r in rooms), 1),
    }


@router.post("/3d/reconstruct")
async def reconstruct_3d_model(
    file: UploadFile = File(..., description="3D model: OBJ / GLB / glTF / STL / PLY / OFF"),
    style: str = Form(default="", description="Optional material/finish hint for the render."),
    user: User = Depends(get_current_user),
) -> dict:
    """Upload a 3D model → decompose it into editable PARTS (Layer 5B, Tier 2).
    Each connected component becomes a positioned/sized/typed object in an
    editable DesignGraph — individually selectable (per-part hotspots), BIM-
    exportable, and listed in the spec-sheet BOM. A welded single-mesh model
    yields one part (true wall/room reconstruction is the deeper Tier 2b)."""
    body = await file.read()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="empty_file", message="The uploaded file is empty.").model_dump())
    try:
        mesh = load_mesh(file.filename or "model", body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_model", message=str(exc)).model_dump())

    graph, parts = reconstruct_from_mesh(
        mesh["verts"], mesh["tris"], "reconstruct", (style.strip() or None))
    if not parts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ErrorResponse(error="unrenderable",
                                 message="The model produced no parts.").model_dump())

    result = await render_parts(parts, style=(style.strip() or None))
    render_payload = None
    if result and result.image_bytes:
        render_payload = {
            "image": f"data:{result.mime};base64,{base64.b64encode(result.image_bytes).decode()}",
            "provider": result.provider, "finished": result.finished, "kind": result.kind,
        }
    spec_sheet = None
    try:
        svg = spec_sheet_svg(graph, {"project_name": file.filename or "Reconstructed model"})
        spec_sheet = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    except Exception as exc:  # noqa: BLE001 — parts already computed
        logger.warning("reconstruct spec sheet failed for %s: %s", file.filename, exc)

    return {
        "filename": file.filename,
        "part_count": len(parts),
        "parts": [{
            "id": p["id"], "type": p["type"],
            "dimensions_mm": {k: round(v * 1000) for k, v in p["dimensions"].items()},
        } for p in parts],
        "graph": graph,                 # editable DesignGraph — objects = the parts
        "render": render_payload,
        "spec_sheet": spec_sheet,
        "hotspots": result.hotspots if result else [],
        "editable": True,
    }


@router.post("/advisor/knowledge")
async def import_advisor_knowledge(
    payload: ImportAdvisorRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Preview the knowledge slice the import-advisor LLM stage will see."""
    try:
        theme_pack = (
            await _get_theme_db(db, payload.theme) if payload.theme else None
        )
        knowledge = build_import_advisor_knowledge(payload, theme_pack=theme_pack)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "import_count": len(payload.imports),
        "supported_extensions": knowledge["schema"]["supported_extensions"],
        "knowledge": knowledge,
    }


@router.post("/advisor")
async def import_advisor_endpoint(
    payload: ImportAdvisorRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run the LLM import-advisor author + return the structured manifest."""
    try:
        return await generate_import_manifest(payload, session=db)
    except ImportAdvisorError as exc:
        msg = str(exc)
        if "No imports provided" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc
