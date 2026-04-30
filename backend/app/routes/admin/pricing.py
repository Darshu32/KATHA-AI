"""Admin pricing endpoints (Stage 1).

Lets ops + senior designers update versioned cost data without touching
Python source. Every write:

- creates a new version row (existing one is demoted to ``is_current=False``)
- writes an :class:`AuditEvent` with before/after diff + actor + reason
- returns the serialised new row

Auth model
----------
Uses the existing :func:`app.middleware.get_current_user` dependency.
Stage 0 ships a dev-user fallback; production deploys should require a
real JWT and (later) RBAC for admin scope.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.observability.request_id import get_request_id
from app.repositories.pricing import (
    CityPriceIndexRepository,
    CostFactorRepository,
    LaborRateRepository,
    MaterialPriceRepository,
    TradeHourRepository,
)

router = APIRouter(prefix="/admin/pricing", tags=["admin", "pricing"])


# ─────────────────────────────────────────────────────────────────────
# Request bodies
# ─────────────────────────────────────────────────────────────────────


class _BandUpdate(BaseModel):
    new_low: float = Field(ge=0)
    new_high: float = Field(ge=0)
    reason: Optional[str] = Field(default=None, max_length=500)


class _MultiplierUpdate(BaseModel):
    new_multiplier: float = Field(gt=0)
    reason: Optional[str] = Field(default=None, max_length=500)


# ─────────────────────────────────────────────────────────────────────
# Material prices
# ─────────────────────────────────────────────────────────────────────


@router.get("/materials")
async def list_materials(
    category: Optional[str] = Query(default=None),
    region: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = MaterialPriceRepository(db)
    rows = await repo.list_active(category=category, region=region)
    return {"materials": rows, "count": len(rows)}


@router.get("/materials/{slug}/history")
async def material_history(
    slug: str,
    region: str = Query(default="global"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = MaterialPriceRepository(db)
    rows = await repo.history_for_slug(slug, region=region)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message=f"No history for slug={slug!r} region={region!r}",
            ).model_dump(),
        )
    return {"slug": slug, "region": region, "versions": rows}


@router.post("/materials/{slug}", status_code=status.HTTP_201_CREATED)
async def update_material_price(
    slug: str,
    payload: _BandUpdate,
    region: str = Query(default="global"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.new_high < payload.new_low:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="bad_input",
                message="new_high must be >= new_low",
            ).model_dump(),
        )
    repo = MaterialPriceRepository(db)
    try:
        new_row = await repo.update_price(
            slug=slug,
            region=region,
            new_low=payload.new_low,
            new_high=payload.new_high,
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


# ─────────────────────────────────────────────────────────────────────
# Labor rates
# ─────────────────────────────────────────────────────────────────────


@router.get("/labor")
async def list_labor_rates(
    region: str = Query(default="india"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = LaborRateRepository(db)
    rows = await repo.list_active(region=region)
    return {"region": region, "rates": rows, "count": len(rows)}


@router.get("/labor/{trade}/history")
async def labor_history(
    trade: str,
    region: str = Query(default="india"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = LaborRateRepository(db)
    rows = await repo.history_for(trade=trade, region=region)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no history")
    return {"trade": trade, "region": region, "versions": rows}


@router.post("/labor/{trade}", status_code=status.HTTP_201_CREATED)
async def update_labor_rate(
    trade: str,
    payload: _BandUpdate,
    region: str = Query(default="india"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = LaborRateRepository(db)
    try:
        new_row = await repo.update_rate(
            trade=trade,
            region=region,
            new_low=payload.new_low,
            new_high=payload.new_high,
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


# ─────────────────────────────────────────────────────────────────────
# Trade hours
# ─────────────────────────────────────────────────────────────────────


@router.get("/trade-hours")
async def list_trade_hours(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = TradeHourRepository(db)
    rows = await repo.list_active()
    return {"trade_hours": rows, "count": len(rows)}


@router.post("/trade-hours/{trade}/{complexity}", status_code=status.HTTP_201_CREATED)
async def update_trade_hours(
    trade: str,
    complexity: str,
    payload: _BandUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = TradeHourRepository(db)
    try:
        new_row = await repo.update_band(
            trade=trade,
            complexity=complexity,
            new_low=payload.new_low,
            new_high=payload.new_high,
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


# ─────────────────────────────────────────────────────────────────────
# City price indices
# ─────────────────────────────────────────────────────────────────────


@router.get("/cities")
async def list_cities(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = CityPriceIndexRepository(db)
    rows = await repo.list_active()
    return {"cities": rows, "count": len(rows)}


@router.post("/cities/{city_slug}", status_code=status.HTTP_201_CREATED)
async def update_city_index(
    city_slug: str,
    payload: _MultiplierUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = CityPriceIndexRepository(db)
    try:
        new_row = await repo.update_multiplier(
            city_slug=city_slug,
            new_multiplier=payload.new_multiplier,
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


# ─────────────────────────────────────────────────────────────────────
# Cost factors
# ─────────────────────────────────────────────────────────────────────


@router.get("/factors")
async def list_factors(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = CostFactorRepository(db)
    rows = await repo.list_active()
    return {"factors": rows, "count": len(rows)}


@router.get("/factors/{factor_key}/history")
async def factor_history(
    factor_key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = CostFactorRepository(db)
    rows = await repo.history_for(factor_key)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no history")
    return {"factor_key": factor_key, "versions": rows}


@router.post("/factors/{factor_key}", status_code=status.HTTP_201_CREATED)
async def update_factor(
    factor_key: str,
    payload: _BandUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = CostFactorRepository(db)
    try:
        new_row = await repo.update_band(
            factor_key=factor_key,
            new_low=payload.new_low,
            new_high=payload.new_high,
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
