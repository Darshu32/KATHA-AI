"""Image generation route — minimal, stateless, production-ready.

POST ``/api/v1/images/generate``
    body  : { prompt, project_type, theme, theme_label?, ratio? }
    -> { status, image: { url, source, type, ... } | null, prompt_assembled }

This is the surface MVP 2's design canvas calls. It's intentionally
narrow — no project persistence, no design graph, no cost estimation.
Just: take inputs, call Nano Banana Pro, return the image URL (or a
clean error envelope when the API key isn't configured yet).

Authenticated. Rate-limited via the global RateLimitMiddleware.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.observability.error_codes import ErrorCode, http_status_for
from app.observability.error_envelope import build_envelope
from app.observability.request_id import get_request_id
from app.repositories.themes import ThemeRepository
from app.services.image_service import generate_image
from app.services.project_types import PROJECT_TYPE_DEFINITIONS

router = APIRouter(prefix="/images", tags=["images"])


_VALID_PROJECT_TYPE_SLUGS = {d["slug"] for d in PROJECT_TYPE_DEFINITIONS}


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=5000)
    project_type: str = Field(default="residential", max_length=64)
    theme: str = Field(default="modern", max_length=64)
    ratio: Optional[str] = Field(default=None, max_length=16)


class ImageGenerateResponse(BaseModel):
    status: str
    image: Optional[dict] = None
    prompt_assembled: Optional[str] = None
    project_type: str
    theme: str


def _bad_request(message: str, code: ErrorCode):
    return HTTPException(
        status_code=http_status_for(code),
        detail=build_envelope(
            code=code, message=message, request_id=get_request_id()
        ),
    )


@router.post("/generate", response_model=ImageGenerateResponse)
async def generate_image_route(
    payload: ImageGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ImageGenerateResponse:
    """Generate one image. Type + theme are encoded into the prompt
    inside :func:`app.services.image_service.generate_image`."""

    project_type = payload.project_type.lower().strip()
    if project_type not in _VALID_PROJECT_TYPE_SLUGS:
        raise _bad_request(
            f"unknown project_type: {payload.project_type!r}",
            ErrorCode.VALIDATION,
        )

    # Look up the theme's display_name so generate_image can fall back
    # to it when an admin-defined theme isn't in the static hint map.
    theme_label: Optional[str] = None
    theme_slug = payload.theme.lower().strip()
    if theme_slug:
        theme_repo = ThemeRepository(db)
        theme_row = await theme_repo.get_active_by_slug(theme_slug)
        if theme_row is not None:
            theme_label = theme_row.get("display_name")

    image = await generate_image(
        payload.prompt,
        project_type=project_type,
        theme=theme_slug,
        theme_label=theme_label,
    )

    if image is None:
        # Clean error envelope — provider not configured. Frontend can
        # render this as a banner without the request "failing".
        return ImageGenerateResponse(
            status="provider_unconfigured",
            image=None,
            project_type=project_type,
            theme=theme_slug,
        )

    return ImageGenerateResponse(
        status="ok",
        image=image,
        project_type=project_type,
        theme=theme_slug,
    )
