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
from app.services.importers.mesh_geometry import load_mesh, supported_mesh_extensions
from app.services.spatial.drawings2d import mesh_spec_sheet_svg
from app.services.spatial.render_pipeline import render_mesh
from app.services.themes import get_theme as _get_theme_db

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
