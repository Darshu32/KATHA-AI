"""Knowledge integration routes (BRD Layer 6).

Two stages — same shape as the rest of the project:

    POST /knowledge/apply/preview  — deterministic slice only (no LLM
                                     call). The UI can use this for
                                     instant inline validation as the
                                     user types.
    POST /knowledge/apply          — live LLM stage that narrates the
                                     deterministic slice into a
                                     full Knowledge Application Report.
    GET  /knowledge/events         — list supported event kinds + the
                                     vocabularies each event accepts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.knowledge import (
    costing,
    ergonomics,
    ibc,
    manufacturing,
    materials,
    regional_materials,
    structural,
    themes,
)
from app.services.standards.knowledge_service import list_standards_by_category
from app.services.knowledge_integration_service import (
    PIECE_COST_BAND_INR_PER_M2,
    _TOLERANCE_FLOORS_MM,
)
from app.models.schemas import ErrorResponse
from app.services.knowledge_integration_service import (
    EVENT_KINDS_IN_SCOPE,
    KnowledgeIntegrationError,
    KnowledgeIntegrationRequest,
    build_knowledge_integration_slice,
    generate_knowledge_application,
)
from app.services.pricing.knowledge_service import load_labor_rate_bands
from app.services.recommendations_service import (
    RecommendationsError,
    RecommendationsRequest,
    build_recommendations_knowledge,
    generate_recommendations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/events")
async def list_events(db: AsyncSession = Depends(get_db)) -> dict:
    """Catalogue of event kinds + the vocabulary the payload may use.

    Room-type vocabularies (residential / commercial / hospitality) are
    now sourced from the ``building_standards`` table (Stage 3B) — the
    old Python-literal ``space_standards`` module is the deprecated
    seed source, not the runtime authority.
    """
    space_rows = await list_standards_by_category(
        db, category="space", jurisdiction="india_nbc"
    )
    _labor_bands = await load_labor_rate_bands(
        db, defaults=costing.LABOR_RATES_INR_PER_HOUR
    )

    def _slugs_for(subcategory: str) -> list[str]:
        return sorted(
            r["slug"] for r in space_rows if r.get("subcategory") == subcategory
        )

    return {
        "event_kinds": list(EVENT_KINDS_IN_SCOPE),
        "vocab": {
            "themes_known": themes.list_names(),
            "room_types_residential": _slugs_for("residential_room"),
            "room_types_commercial": _slugs_for("commercial_room"),
            "room_types_hospitality": _slugs_for("hospitality_room"),
            "wood_species_known": sorted(list(materials.WOOD.keys())),
            "metals_known": sorted(list(materials.METALS.keys())),
            "finishes_known": sorted(list(materials.FINISHES.keys())),
            "ergo_categories": ["chair", "table", "bed", "storage"],
            "ergo_chairs_known": sorted(list(ergonomics.CHAIRS.keys())),
            "ergo_tables_known": sorted(list(ergonomics.TABLES.keys())),
            "ergo_beds_known": sorted(list(ergonomics.BEDS.keys())),
            "ergo_storage_known": sorted(list(ergonomics.STORAGE.keys())),
            "joinery_methods_known": sorted(list(manufacturing.JOINERY.keys())),
            "quantity_basis_in_scope": ["kg", "m2", "m3", "linear_m", "piece"],
            "complexity_levels_in_scope": ["simple", "moderate", "complex", "highly_complex"],
            "waste_factor_pct_band_brd": list(costing.WASTE_FACTOR_PCT),
            "finish_pct_of_material_brd": list(costing.FINISH_COST_PCT_OF_MATERIAL),
            "labor_trades_known": sorted(list(_labor_bands.keys())),
            "cities_known": sorted(list(regional_materials.CITY_PRICE_INDEX.keys())),
            "volume_tiers_known": list(costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.keys()),
            "load_use_types_known": sorted(list(structural.LIVE_LOADS_KN_PER_M2.keys())),
            "span_materials_known": sorted(list(structural.SPAN_LIMITS_M.keys())),
            "ibc_occupancy_groups_known": sorted(list(ibc.OCCUPANCY_GROUPS.keys())),
            "tolerance_band_keys_known": list(_TOLERANCE_FLOORS_MM.keys()),
            "piece_types_with_cost_band": sorted(list(PIECE_COST_BAND_INR_PER_M2.keys())),
        },
    }


@router.post("/apply/preview")
async def apply_preview(
    payload: KnowledgeIntegrationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deterministic slice only — instant inline validation, no LLM call."""
    try:
        labor_bands = await load_labor_rate_bands(
            db, defaults=costing.LABOR_RATES_INR_PER_HOUR
        )
        knowledge = build_knowledge_integration_slice(
            payload, labor_rates=labor_bands
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "event_kind": payload.event_kind,
        "application": knowledge["application"],
        "knowledge": knowledge,
    }


@router.post("/recommendations/preview")
async def recommendations_preview(payload: RecommendationsRequest) -> dict:
    """Deterministic knowledge slice — no LLM call. UI can use for live hints."""
    try:
        knowledge = build_recommendations_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "theme": payload.theme,
        "piece_type": payload.piece_type,
        "knowledge": knowledge,
    }


@router.post("/recommendations")
async def recommendations_endpoint(payload: RecommendationsRequest) -> dict:
    """Run the LLM recommendations author + return ranked suggestions."""
    try:
        return await generate_recommendations(payload)
    except RecommendationsError as exc:
        msg = str(exc)
        code = status.HTTP_503_SERVICE_UNAVAILABLE
        err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/apply")
async def apply_event(
    payload: KnowledgeIntegrationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run the LLM knowledge-integration author + return the structured report."""
    try:
        return await generate_knowledge_application(payload, session=db)
    except KnowledgeIntegrationError as exc:
        msg = str(exc)
        if msg.startswith("Unknown event_kind"):
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc
