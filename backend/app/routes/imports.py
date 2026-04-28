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

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.schemas import ErrorResponse
from app.services.import_advisor_service import (
    ImportAdvisorError,
    ImportAdvisorRequest,
    build_import_advisor_knowledge,
    generate_import_manifest,
)
from app.services.importers import parse as parse_file
from app.services.importers import supported_extensions

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


@router.post("/advisor/knowledge")
async def import_advisor_knowledge(payload: ImportAdvisorRequest) -> dict:
    """Preview the knowledge slice the import-advisor LLM stage will see."""
    try:
        knowledge = build_import_advisor_knowledge(payload)
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
async def import_advisor_endpoint(payload: ImportAdvisorRequest) -> dict:
    """Run the LLM import-advisor author + return the structured manifest."""
    try:
        return await generate_import_manifest(payload)
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
