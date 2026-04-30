"""Admin theme endpoints (Stage 3A).

Endpoints for senior designers to:

- list / inspect every theme (including drafts)
- view full version history
- update a rule pack — produces a new version
- clone an existing theme into a fresh logical record (draft status)
- transition status (draft → published → archived)

Auth: every endpoint goes through :func:`get_current_user`. Stage 13
adds RBAC so only ``role=designer-admin`` users can write.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.observability.request_id import get_request_id
from app.repositories.themes import ThemeRepository

router = APIRouter(prefix="/admin/themes", tags=["admin", "themes"])


# ─────────────────────────────────────────────────────────────────────
# Request bodies
# ─────────────────────────────────────────────────────────────────────


class _RulePackUpdate(BaseModel):
    rule_pack: dict[str, Any]
    display_name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    aliases: Optional[list[str]] = Field(default=None)
    reason: Optional[str] = Field(default=None, max_length=500)


class _StatusUpdate(BaseModel):
    new_status: str = Field(description="draft | published | archived")
    reason: Optional[str] = Field(default=None, max_length=500)


class _CloneRequest(BaseModel):
    new_slug: str = Field(min_length=1, max_length=64)
    new_display_name: str = Field(min_length=1, max_length=120)
    reason: Optional[str] = Field(default=None, max_length=500)


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_themes(
    status: Optional[str] = Query(
        default=None,
        description=(
            "Filter by status. Default (no value): published only. "
            "Pass 'all' to include drafts + archived."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = ThemeRepository(db)
    if status == "all":
        rows = await repo.list_active(status=None)
    elif status in {"draft", "published", "archived"}:
        rows = await repo.list_active(status=status)
    else:
        rows = await repo.list_active(status="published")
    return {"themes": rows, "count": len(rows)}


@router.get("/{slug}")
async def get_theme_admin(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """Resolve a theme — admin variant returns drafts too."""
    repo = ThemeRepository(db)
    row = await repo.get_active_by_slug_admin(slug)
    if row is None:
        raise HTTPException(
            status_code=status_code_404(),
            detail=ErrorResponse(
                error="not_found", message=f"No theme for slug={slug!r}"
            ).model_dump(),
        )
    return {"theme": row}


@router.get("/{slug}/history")
async def theme_history(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = ThemeRepository(db)
    rows = await repo.history_for_slug(slug)
    if not rows:
        raise HTTPException(
            status_code=status_code_404(),
            detail=ErrorResponse(
                error="not_found", message=f"No history for slug={slug!r}"
            ).model_dump(),
        )
    return {"slug": slug, "versions": rows}


# ─────────────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────────────


@router.post("/{slug}", status_code=status.HTTP_201_CREATED)
async def update_theme(
    slug: str,
    payload: _RulePackUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = ThemeRepository(db)
    try:
        new_row = await repo.update_rule_pack(
            slug=slug,
            new_rule_pack=payload.rule_pack,
            new_display_name=payload.display_name,
            new_description=payload.description,
            new_aliases=payload.aliases,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status_code_404(),
            detail=ErrorResponse(error="not_found", message=str(exc)).model_dump(),
        ) from exc
    return {"new_version": new_row}


@router.post("/{slug}/status", status_code=status.HTTP_201_CREATED)
async def transition_status(
    slug: str,
    payload: _StatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = ThemeRepository(db)
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
            status_code_404()
            if isinstance(exc, LookupError)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error="invalid_input", message=str(exc)).model_dump(),
        ) from exc
    return {"new_version": new_row}


@router.post("/{source_slug}/clone", status_code=status.HTTP_201_CREATED)
async def clone_theme(
    source_slug: str,
    payload: _CloneRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Create a new theme by cloning an existing one.

    The new theme starts in ``draft`` status. Designers iterate, then
    transition to ``published`` via ``POST /admin/themes/<slug>/status``.
    """
    repo = ThemeRepository(db)
    try:
        new_row = await repo.clone_theme(
            source_slug=source_slug,
            new_slug=payload.new_slug,
            new_display_name=payload.new_display_name,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status_code_404(),
            detail=ErrorResponse(error="not_found", message=str(exc)).model_dump(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorResponse(error="conflict", message=str(exc)).model_dump(),
        ) from exc
    return {"clone": new_row}


def status_code_404() -> int:
    return status.HTTP_404_NOT_FOUND
