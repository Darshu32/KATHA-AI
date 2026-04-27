"""Working-drawings routes (BRD Layer 3A — auto-generated technical drawings).

Each drawing type follows the project contract:
  validated request → injected knowledge → live LLM call → deterministic
  CAD-style renderer using the LLM spec → annotated SVG + structured spec.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.knowledge import themes
from app.models.schemas import ErrorResponse
from app.services.detail_sheet_drawing_service import (
    DetailSheetError,
    DetailSheetRequest,
    build_detail_knowledge,
    generate_detail_sheet_drawing,
)
from app.services.precision_validator import (
    precision_bands,
    precision_compliance_report,
)
from app.services.elevation_view_drawing_service import (
    ElevationViewError,
    ElevationViewRequest,
    build_elevation_knowledge,
    generate_elevation_view_drawing,
)
from app.services.isometric_view_drawing_service import (
    IsometricViewError,
    IsometricViewRequest,
    build_isometric_knowledge,
    generate_isometric_view_drawing,
)
from app.services.plan_view_drawing_service import (
    PlanViewError,
    PlanViewRequest,
    build_plan_knowledge,
    generate_plan_view_drawing,
)
from app.services.section_view_drawing_service import (
    SectionViewError,
    SectionViewRequest,
    build_section_knowledge,
    generate_section_view_drawing,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/working-drawings", tags=["working-drawings"])


@router.get("/precision-requirements")
async def precision_requirements_endpoint() -> dict:
    """Expose BRD 3A precision-requirement bands dynamically — no hardcoded list."""
    return {
        "bands_mm": precision_bands(),
        "applies_to": [
            {"category": "structural_mm", "examples": ["load-bearing joints", "frame members"]},
            {"category": "cosmetic_mm", "examples": ["visible surfaces", "panels", "edges"]},
            {"category": "material_thickness_mm", "examples": ["sheet stock", "veneer", "upholstery foam batt"]},
            {"category": "hardware_placement_mm", "examples": ["knobs", "handles", "hinge centre lines"]},
        ],
        "qa_gate": "dimension_verification",
    }


@router.get("/types")
async def list_drawing_types() -> dict:
    """Dynamic catalogue — grows as 3A sub-bullets land."""
    return {
        "drawings": [
            {
                "id": "plan_view",
                "name": "Plan View",
                "stage": "BRD 3A #1",
                "summary": "Top-down — overall dims, key measurements, section refs, material hatches, scale bar.",
            },
            {
                "id": "elevation_view",
                "name": "Elevation View",
                "stage": "BRD 3A #2",
                "summary": "Front/side projection — seat/back/overall heights, leg-base proportions, hardware + detail callouts.",
            },
            {
                "id": "section_view",
                "name": "Section View",
                "stage": "BRD 3A #3",
                "summary": "Cut-through — internal layers, joints + reinforcement, seat depth, back angle, leg taper.",
            },
            {
                "id": "isometric_view",
                "name": "Isometric View",
                "stage": "BRD 3A #4",
                "summary": "3D iso/perspective — overall form, material finishes, optional explode, superimposed dims.",
            },
            {
                "id": "detail_sheet",
                "name": "Detail Sheet",
                "stage": "BRD 3A #5",
                "summary": "Zoomed details — joints, hardware, edge profiles, seams, material transitions; per-cell scale.",
            },
        ]
    }


@router.post("/plan-view/knowledge")
async def plan_view_knowledge(payload: PlanViewRequest) -> dict:
    """Preview the knowledge slice the plan-view LLM stage will see."""
    knowledge = build_plan_knowledge(payload)
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


def _attach_precision(result: dict, spec_key: str) -> dict:
    """Add a BRD 3A precision-compliance report to a drawing endpoint response."""
    result["precision_compliance"] = precision_compliance_report(
        drawing_id=spec_key,
        spec=result.get(spec_key),
    )
    return result


@router.post("/plan-view")
async def plan_view_endpoint(payload: PlanViewRequest) -> dict:
    """Run the LLM plan-view author + render the technical SVG."""
    try:
        return _attach_precision(await generate_plan_view_drawing(payload), "plan_view_spec")
    except PlanViewError as exc:
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


@router.post("/elevation-view/knowledge")
async def elevation_view_knowledge(payload: ElevationViewRequest) -> dict:
    """Preview the knowledge slice the elevation-view LLM stage will see."""
    knowledge = build_elevation_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    if not knowledge.get("piece_envelope"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="no_envelope",
                message="Provide either a piece or a design_graph (or parametric_spec.geometry) to project.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/elevation-view")
async def elevation_view_endpoint(payload: ElevationViewRequest) -> dict:
    """Run the LLM elevation-view author + render the technical SVG."""
    try:
        return _attach_precision(await generate_elevation_view_drawing(payload), "elevation_view_spec")
    except ElevationViewError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        elif "No piece envelope" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "no_envelope"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/section-view/knowledge")
async def section_view_knowledge(payload: SectionViewRequest) -> dict:
    """Preview the knowledge slice the section-view LLM stage will see."""
    knowledge = build_section_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    if not knowledge.get("piece_envelope"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="no_envelope",
                message="Provide an explicit piece envelope to cut through.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/section-view")
async def section_view_endpoint(payload: SectionViewRequest) -> dict:
    """Run the LLM section-view author + render the cut-through SVG."""
    try:
        return _attach_precision(await generate_section_view_drawing(payload), "section_view_spec")
    except SectionViewError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        elif "No piece envelope" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "no_envelope"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/isometric/knowledge")
async def isometric_knowledge(payload: IsometricViewRequest) -> dict:
    """Preview the knowledge slice the iso LLM stage will see."""
    knowledge = build_isometric_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    if not knowledge.get("piece_envelope"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="no_envelope",
                message="Provide an explicit piece envelope to project.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/isometric")
async def isometric_endpoint(payload: IsometricViewRequest) -> dict:
    """Run the LLM iso author + render the 3D axonometric SVG."""
    try:
        return _attach_precision(await generate_isometric_view_drawing(payload), "isometric_view_spec")
    except IsometricViewError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        elif "No piece envelope" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "no_envelope"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/detail-sheet/knowledge")
async def detail_sheet_knowledge(payload: DetailSheetRequest) -> dict:
    """Preview the knowledge slice the detail-sheet LLM stage will see."""
    knowledge = build_detail_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No theme rule pack for '{payload.theme}'.",
            ).model_dump(),
        )
    if not knowledge.get("piece_envelope"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="no_envelope",
                message="Provide an explicit piece envelope to detail.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "available_themes": themes.list_names(),
        "knowledge": knowledge,
    }


@router.post("/detail-sheet")
async def detail_sheet_endpoint(payload: DetailSheetRequest) -> dict:
    """Run the LLM detail-sheet author + render the multi-cell detail SVG."""
    try:
        return _attach_precision(await generate_detail_sheet_drawing(payload), "detail_sheet_spec")
    except DetailSheetError as exc:
        msg = str(exc)
        if "Unknown theme" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_theme"
        elif "No piece envelope" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "no_envelope"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc
