"""Admin suggestions endpoints (Stage 3F).

CRUD on chip catalog with versioning + audit. Designers use these to
rotate chips for A/B tests, adjust weights, transition status,
change copy.

Auth: every endpoint goes through :func:`get_current_user`. Stage 13
adds RBAC for ``role=designer-admin``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.observability.request_id import get_request_id
from app.repositories.suggestions import SuggestionRepository

router = APIRouter(prefix="/admin/suggestions", tags=["admin", "suggestions"])


# ─────────────────────────────────────────────────────────────────────
# Bodies
# ─────────────────────────────────────────────────────────────────────


class _SuggestionCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=5000)
    description: Optional[str] = Field(default=None, max_length=500)
    contexts: list[str] = Field(default_factory=list)
    weight: int = Field(default=100, ge=0, le=1000)
    status: str = Field(default="draft", description="draft | published | archived")
    tags: Optional[list[str]] = Field(default=None)
    reason: Optional[str] = Field(default=None, max_length=500)


class _SuggestionUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    prompt: Optional[str] = Field(default=None, max_length=5000)
    description: Optional[str] = Field(default=None, max_length=500)
    contexts: Optional[list[str]] = Field(default=None)
    weight: Optional[int] = Field(default=None, ge=0, le=1000)
    tags: Optional[list[str]] = Field(default=None)
    reason: Optional[str] = Field(default=None, max_length=500)


class _StatusUpdate(BaseModel):
    new_status: str = Field(description="draft | published | archived")
    reason: Optional[str] = Field(default=None, max_length=500)


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_suggestions(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    if status_filter == "all":
        rows = await repo.list_admin(status=None)
    elif status_filter in {"draft", "published", "archived"}:
        rows = await repo.list_admin(status=status_filter)
    else:
        rows = await repo.list_admin(status=None)
    return {"suggestions": rows, "count": len(rows)}


@router.get("/{slug}")
async def get_suggestion(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    row = await repo.get_by_slug(slug, published_only=False)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message=f"No suggestion for slug={slug!r}",
            ).model_dump(),
        )
    return {"suggestion": row}


@router.get("/{slug}/history")
async def suggestion_history(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    rows = await repo.history_for(slug)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(error="not_found", message="no history").model_dump(),
        )
    return {"slug": slug, "versions": rows}


# ─────────────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_suggestion(
    payload: _SuggestionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    try:
        new_row = await repo.create_new(
            slug=payload.slug,
            label=payload.label,
            prompt=payload.prompt,
            description=payload.description,
            contexts=payload.contexts,
            weight=payload.weight,
            status=payload.status,
            tags=payload.tags,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(error="conflict", message=str(exc)).model_dump(),
        ) from exc
    return {"created": new_row}


@router.post("/{slug}", status_code=status.HTTP_201_CREATED)
async def update_suggestion(
    slug: str,
    payload: _SuggestionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    try:
        new_row = await repo.update(
            slug=slug,
            label=payload.label,
            prompt=payload.prompt,
            description=payload.description,
            contexts=payload.contexts,
            weight=payload.weight,
            tags=payload.tags,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(error="not_found", message=str(exc)).model_dump(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {"new_version": new_row}


@router.post("/{slug}/status", status_code=status.HTTP_201_CREATED)
async def transition_status(
    slug: str,
    payload: _StatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = SuggestionRepository(db)
    try:
        new_row = await repo.update_status(
            slug=slug,
            new_status=payload.new_status,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except (LookupError, ValueError) as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, LookupError)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error="invalid_input", message=str(exc)).model_dump(),
        ) from exc
    return {"new_version": new_row}
