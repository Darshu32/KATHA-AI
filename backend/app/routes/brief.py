"""Design Brief intake route (BRD Phase 1 / Layer 1A)."""

import logging

from fastapi import APIRouter, HTTPException, status

from app.models.brief import DesignBriefIn, DesignBriefOut
from app.models.schemas import ErrorDetail, ErrorResponse
from app.services.design_brief_service import (
    brief_to_generation_context,
    validate_and_normalize,
)
from app.services.architect_brief_service import (
    ArchitectBriefError,
    generate_architect_brief,
)
from app.services.knowledge_injector import (
    build_prompt_preamble,
    inject_knowledge,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brief", tags=["brief"])


@router.post(
    "/intake",
    response_model=DesignBriefOut,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def intake_brief(payload: DesignBriefIn) -> DesignBriefOut:
    """Validate and normalize a five-section design brief."""
    try:
        return validate_and_normalize(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="invalid_brief",
                message=str(exc),
                details=[ErrorDetail(message=str(exc))],
            ).model_dump(),
        ) from exc


@router.post("/context")
async def brief_context(payload: DesignBriefIn) -> dict:
    """Return the flattened generation-pipeline context for a given brief."""
    normalized = validate_and_normalize(payload)
    return {
        "brief_id": normalized.brief_id,
        "warnings": normalized.warnings,
        "context": brief_to_generation_context(normalized),
    }


@router.post("/knowledge")
async def brief_knowledge(payload: DesignBriefIn) -> dict:
    """Return the input-stage knowledge bundle injected for this brief.

    Covers standard dimensions, applicable building codes, climate-specific
    considerations, and material availability/pricing by region.
    """
    normalized = validate_and_normalize(payload)
    bundle = inject_knowledge(normalized)
    return {
        "brief_id": normalized.brief_id,
        "warnings": normalized.warnings,
        "knowledge": bundle,
        "prompt_preamble": build_prompt_preamble(normalized, bundle),
    }


@router.post("/architect")
async def brief_architect(payload: DesignBriefIn) -> dict:
    """Run the LLM architect-brief stage.

    Enforces the project contract: validated brief → injected Layer 1B
    knowledge preamble → live LLM call → structured architect brief.
    """
    normalized = validate_and_normalize(payload)
    try:
        result = await generate_architect_brief(normalized)
    except ArchitectBriefError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorResponse(
                error="llm_unavailable",
                message=str(exc),
            ).model_dump(),
        ) from exc
    result["warnings"] = normalized.warnings
    return result
