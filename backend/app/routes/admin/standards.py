"""Admin standards endpoints (Stage 3B).

Endpoints for compliance officers + senior architects to:

- list standards by category and jurisdiction
- view full version history of a logical key
- update a rule's data, notes, source citation
- (creating brand-new standards is supported via the same POST —
  it appends a new version of an existing logical key only.
  To add a fresh logical key, run a migration; see ``docs/data/standards.md``.)

Logical key
-----------
Every endpoint accepts the triple ``(slug, category, jurisdiction)``
and defaults ``jurisdiction`` to ``india_nbc`` (BRD baseline).
Jurisdiction-specific overrides (e.g. ``maharashtra_dcr``) live as
their own rows; the resolver in :class:`StandardsRepository.resolve`
falls back to baseline.
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
from app.repositories.standards import StandardsRepository

router = APIRouter(prefix="/admin/standards", tags=["admin", "standards"])


# ─────────────────────────────────────────────────────────────────────
# Bodies
# ─────────────────────────────────────────────────────────────────────


class _StandardUpdate(BaseModel):
    data: dict[str, Any] = Field(
        description="Full new data dict — replaces the existing one."
    )
    display_name: Optional[str] = Field(default=None, max_length=160)
    notes: Optional[str] = Field(default=None, max_length=2000)
    source_section: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=500)


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_standards(
    category: Optional[str] = Query(default=None, description="clearance | space | mep | code"),
    subcategory: Optional[str] = Query(default=None),
    jurisdiction: str = Query(default="india_nbc"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = StandardsRepository(db)
    rows = await repo.list_active(
        category=category, subcategory=subcategory, jurisdiction=jurisdiction
    )
    return {
        "standards": rows,
        "count": len(rows),
        "filter": {
            "category": category,
            "subcategory": subcategory,
            "jurisdiction": jurisdiction,
        },
    }


@router.get("/{category}/{slug}")
async def get_standard_admin(
    category: str,
    slug: str,
    jurisdiction: str = Query(default="india_nbc"),
    resolve: bool = Query(
        default=False,
        description=(
            "If true, fall back to the india_nbc baseline when the "
            "requested jurisdiction has no specific row."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = StandardsRepository(db)
    if resolve:
        row = await repo.resolve(slug=slug, category=category, jurisdiction=jurisdiction)
    else:
        row = await repo.get_active(slug=slug, category=category, jurisdiction=jurisdiction)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message=(
                    f"No standard for slug={slug!r} category={category!r} "
                    f"jurisdiction={jurisdiction!r}"
                ),
            ).model_dump(),
        )
    return {"standard": row}


@router.get("/{category}/{slug}/history")
async def standard_history(
    category: str,
    slug: str,
    jurisdiction: str = Query(default="india_nbc"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = StandardsRepository(db)
    rows = await repo.history_for(
        slug=slug, category=category, jurisdiction=jurisdiction
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(error="not_found", message="no history").model_dump(),
        )
    return {
        "slug": slug,
        "category": category,
        "jurisdiction": jurisdiction,
        "versions": rows,
    }


# ─────────────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────────────


@router.post("/{category}/{slug}", status_code=status.HTTP_201_CREATED)
async def update_standard(
    category: str,
    slug: str,
    payload: _StandardUpdate,
    jurisdiction: str = Query(default="india_nbc"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = StandardsRepository(db)
    try:
        new_row = await repo.update_data(
            slug=slug,
            category=category,
            jurisdiction=jurisdiction,
            new_data=payload.data,
            new_notes=payload.notes,
            new_display_name=payload.display_name,
            new_source_section=payload.source_section,
            actor_id=user.id,
            reason=payload.reason,
            request_id=get_request_id(),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(error="not_found", message=str(exc)).model_dump(),
        ) from exc
    return {"new_version": new_row}
