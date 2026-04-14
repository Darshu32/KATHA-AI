"""Design intake route for validated generation requests."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import DesignOut, DesignRequest, DesignResponse, ErrorDetail, ErrorResponse
from app.services.design_service import create_design, get_design_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design", tags=["design"])


def _error_response(error: str, message: str, *, field: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ErrorResponse(
            error=error,
            message=message,
            details=[ErrorDetail(field=field, message=message)] if field else [],
        ).model_dump(),
    )


@router.post(
    "/generate",
    response_model=DesignResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
)
async def generate_design_request(
    payload: DesignRequest,
    db: AsyncSession = Depends(get_db),
) -> DesignResponse:
    """
    Validate, normalize, and persist the design request before the async pipeline
    moves it from accepted to processing/completed/failed.
    """
    try:
        design = await create_design(db, payload)
        return DesignResponse(
            designId=design.id,
            status=design.status,
            message="Design generation started",
            createdAt=design.created_at,
        )
    except ValueError as exc:
        raise _error_response("invalid_input", str(exc), field="dimensions") from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive API guard
        logger.exception("Failed to accept design request", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                error="server_error",
                message="Unable to start design generation",
            ).model_dump(),
        ) from exc


@router.get(
    "/{design_id}",
    response_model=DesignOut,
    responses={
        404: {"model": ErrorResponse, "description": "Design not found"},
    },
)
async def get_design_request(
    design_id: str,
    db: AsyncSession = Depends(get_db),
) -> DesignOut:
    design = await get_design_by_id(db, design_id)
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message="Design not found",
            ).model_dump(),
        )

    return DesignOut.model_validate(design)
