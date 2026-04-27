"""Technical specification routes (BRD Layer 3B onwards).

Each spec sheet follows the project contract:
  validated request → injected knowledge → live LLM call → validation
  against the same knowledge → structured spec sheet response.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.knowledge import themes
from app.models.schemas import ErrorResponse
from app.services.manufacturing_spec_service import (
    ManufacturingSpecError,
    ManufacturingSpecRequest,
    build_manufacturing_spec_knowledge,
    generate_manufacturing_spec,
)
from app.services.material_spec_service import (
    MaterialSpecError,
    MaterialSpecRequest,
    build_material_spec_knowledge,
    generate_material_spec_sheet,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/specs", tags=["specs"])


@router.get("/types")
async def list_spec_types() -> dict:
    """Dynamic catalogue — grows as 3B / 3C / 3D bullets land."""
    return {
        "specs": [
            {
                "id": "material_spec_sheet",
                "name": "Material Specification Sheet",
                "stage": "BRD 3B",
                "summary": "Per-slot material decisions — grade, finish, colour, supplier, lead time, cost.",
                "sections_implemented": [
                    "primary_structure",
                    "secondary_materials",
                    "hardware",
                    "upholstery",
                    "finishing",
                    "cost_summary",
                ],
            },
            {
                "id": "manufacturing_spec",
                "name": "Manufacturing Specification",
                "stage": "BRD 3C",
                "summary": "Fabricator-facing notes — precision, joinery, finishing sequence, QA gates, lead time.",
                "sections_implemented": [
                    "woodworking_notes",
                    "metal_fabrication_notes",
                    "upholstery_assembly_notes",
                    "quality_assurance",
                ],
            },
        ]
    }


@router.post("/material-spec/knowledge")
async def material_spec_knowledge(payload: MaterialSpecRequest) -> dict:
    """Preview the knowledge slice the material-spec LLM stage will see."""
    knowledge = build_material_spec_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/material-spec")
async def material_spec_endpoint(payload: MaterialSpecRequest) -> dict:
    """Run the LLM material-spec author + return the structured sheet."""
    try:
        return await generate_material_spec_sheet(payload)
    except MaterialSpecError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/manufacturing-spec/knowledge")
async def manufacturing_spec_knowledge(payload: ManufacturingSpecRequest) -> dict:
    """Preview the knowledge slice the manufacturing-spec LLM stage will see."""
    knowledge = build_manufacturing_spec_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/manufacturing-spec")
async def manufacturing_spec_endpoint(payload: ManufacturingSpecRequest) -> dict:
    """Run the LLM manufacturing-spec author + return the structured sheet."""
    try:
        return await generate_manufacturing_spec(payload)
    except ManufacturingSpecError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc
