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
from app.services.mep_spec_service import (
    MEPSpecError,
    MEPSpecRequest,
    build_mep_spec_knowledge,
    generate_mep_spec,
)
from app.services.cost_engine_service import (
    CostEngineError,
    CostEngineRequest,
    build_cost_engine_knowledge,
    generate_cost_engine,
)
from app.services.pricing_service import (
    PricingError,
    PricingRequest,
    build_pricing_knowledge,
    generate_pricing_buildup,
)
from app.services.cost_breakdown_service import (
    CostBreakdownError,
    CostBreakdownRequest,
    build_cost_breakdown_knowledge,
    generate_cost_breakdown,
)
from app.services.sensitivity_service import (
    SensitivityError,
    SensitivityRequest,
    build_sensitivity_knowledge,
    generate_sensitivity_analysis,
)
from app.services.export_advisor_service import (
    ExportAdvisorError,
    ExportAdvisorRequest,
    build_export_advisor_knowledge,
    generate_export_manifest,
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
            {
                "id": "mep_spec",
                "name": "MEP Specification",
                "stage": "BRD 3D",
                "summary": (
                    "MEP-consultant sheet — room volume, ACH, CFM, ductwork, "
                    "supply/return registers, equipment tonnage + BTU, lighting "
                    "+ panel circuits, plumbing fixtures + DFU + drain size, "
                    "and indicative system cost."
                ),
                "sections_implemented": [
                    "hvac",
                    "electrical",
                    "plumbing",
                    "cost",
                ],
            },
            {
                "id": "export_manifest",
                "name": "Export Manifest",
                "stage": "BRD 5A",
                "summary": (
                    "LLM-authored cover letter for the export pack — lists "
                    "every registered file format (PDF / DOCX / XLSX / DXF "
                    "/ OBJ / GLTF / FBX / IFC / STEP / IGES / GCODE / "
                    "GeoJSON) with capabilities, recipient-by-recipient "
                    "recommendations, and a primary handoff format."
                ),
                "sections_implemented": [
                    "format_catalogue",
                    "recipient_recommendations",
                    "handoff_pack",
                    "warnings",
                ],
            },
            {
                "id": "sensitivity_analysis",
                "name": "Sensitivity Analysis",
                "stage": "BRD 4D",
                "summary": (
                    "What-if shocks (+10 % to material / labor / overhead) "
                    "with their impact on final retail price, plus per-unit "
                    "retail at multiple production volumes (manufacturer "
                    "margin re-banded by volume tier)."
                ),
                "sections_implemented": [
                    "shock_table",
                    "volume_table",
                    "ranking",
                    "summary_bullets",
                ],
            },
            {
                "id": "cost_breakdown",
                "name": "Cost Breakdown Report",
                "stage": "BRD 4C",
                "summary": (
                    "Client-facing five-row summary — material, labor, "
                    "overhead, margin (with per-layer breakdown), retail "
                    "price. Each row carries ₹ amount + % of retail. "
                    "Reconciles end-to-end against 4A and 4B."
                ),
                "sections_implemented": [
                    "material_cost",
                    "labor_cost",
                    "overhead",
                    "margin",
                    "retail_price",
                    "reconciliation",
                ],
            },
            {
                "id": "pricing_buildup",
                "name": "Markup & Pricing Buildup",
                "stage": "BRD 4B",
                "summary": (
                    "Walks TOTAL MANUFACTURING COST through the BRD margin "
                    "stack to FINAL RETAIL PRICE — manufacturer margin "
                    "30–60 % by volume tier, designer margin 25–50 % when "
                    "outsourced, retail markup 40–100 % when selling direct, "
                    "customization premium 10–25 % by bespoke level."
                ),
                "sections_implemented": [
                    "manufacturer_margin",
                    "designer_margin",
                    "retail_markup",
                    "customization_premium",
                    "final_retail_price",
                ],
            },
            {
                "id": "cost_engine",
                "name": "Parametric Cost Engine",
                "stage": "BRD 4A",
                "summary": (
                    "Per-piece cost breakdown — material (qty × unit rate + "
                    "waste 10–15 % + finish 15–25 % + hardware ₹500–2 000), "
                    "labor (hours × rate × city index, by trade × complexity), "
                    "overhead (workshop 30–40 %, QC 5–10 % of labor, "
                    "packaging 10–15 % of product cost), TOTAL MANUFACTURING "
                    "COST. Margin / markup is layered separately in 4B."
                ),
                "sections_implemented": [
                    "material_cost",
                    "labor_cost",
                    "overhead",
                    "total_manufacturing_cost",
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


@router.post("/mep-spec/knowledge")
async def mep_spec_knowledge(payload: MEPSpecRequest) -> dict:
    """Preview the knowledge slice the MEP-spec LLM stage will see."""
    try:
        knowledge = build_mep_spec_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "room_use_type": payload.room_use_type,
        "knowledge": knowledge,
    }


@router.post("/mep-spec")
async def mep_spec_endpoint(payload: MEPSpecRequest) -> dict:
    """Run the LLM MEP-spec author + return the structured sheet."""
    try:
        return await generate_mep_spec(payload)
    except MEPSpecError as exc:
        msg = str(exc)
        if msg.startswith("Unknown room_use_type") or msg.startswith("Unknown plumbing fixture"):
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/cost-engine/knowledge")
async def cost_engine_knowledge(payload: CostEngineRequest) -> dict:
    """Preview the BRD knowledge slice the cost-engine LLM stage will see."""
    try:
        knowledge = build_cost_engine_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "piece_name": payload.piece_name,
        "complexity": payload.complexity,
        "knowledge": knowledge,
    }


@router.post("/cost-engine")
async def cost_engine_endpoint(payload: CostEngineRequest) -> dict:
    """Run the LLM cost-engine author + return the structured sheet."""
    try:
        return await generate_cost_engine(payload)
    except CostEngineError as exc:
        msg = str(exc)
        if msg.startswith("Unknown complexity") or msg.startswith("Unknown market_segment"):
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/pricing/knowledge")
async def pricing_knowledge(payload: PricingRequest) -> dict:
    """Preview the BRD margin/markup knowledge slice the pricing LLM will see."""
    try:
        knowledge = build_pricing_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "piece_name": payload.piece_name,
        "manufacturing_cost_inr": payload.manufacturing_cost_inr,
        "knowledge": knowledge,
    }


@router.post("/pricing")
async def pricing_endpoint(payload: PricingRequest) -> dict:
    """Run the LLM pricing-buildup author + return the structured price walk."""
    try:
        return await generate_pricing_buildup(payload)
    except PricingError as exc:
        msg = str(exc)
        if msg.startswith("Unknown"):
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/cost-breakdown/knowledge")
async def cost_breakdown_knowledge(payload: CostBreakdownRequest) -> dict:
    """Preview the rolled-up components the cost-breakdown LLM stage will see."""
    try:
        knowledge = build_cost_breakdown_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "piece_name": payload.piece_name,
        "components": knowledge["components"],
        "knowledge": knowledge,
    }


@router.post("/cost-breakdown")
async def cost_breakdown_endpoint(payload: CostBreakdownRequest) -> dict:
    """Run the LLM cost-breakdown author + return the structured five-row report."""
    try:
        return await generate_cost_breakdown(payload)
    except CostBreakdownError as exc:
        msg = str(exc)
        if "missing or zero" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/sensitivity/knowledge")
async def sensitivity_knowledge(payload: SensitivityRequest) -> dict:
    """Preview the deterministic shock + volume scenarios the LLM stage will see."""
    try:
        knowledge = build_sensitivity_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "piece_name": payload.piece_name,
        "shock_pct": payload.shock_pct,
        "volumes": payload.volumes,
        "knowledge": knowledge,
    }


@router.post("/sensitivity")
async def sensitivity_endpoint(payload: SensitivityRequest) -> dict:
    """Run the LLM sensitivity-analysis author + return the structured what-if report."""
    try:
        return await generate_sensitivity_analysis(payload)
    except SensitivityError as exc:
        msg = str(exc)
        if "missing or zero" in msg or "must be positive" in msg:
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc


@router.post("/export-advisor/knowledge")
async def export_advisor_knowledge(payload: ExportAdvisorRequest) -> dict:
    """Preview the format catalogue + readiness slice the export-advisor LLM stage will see."""
    try:
        knowledge = build_export_advisor_knowledge(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(error="bad_input", message=str(exc)).model_dump(),
        ) from exc
    return {
        "recipients": payload.recipients,
        "registered_format_keys": knowledge["registered_format_keys"],
        "knowledge": knowledge,
    }


@router.post("/export-advisor")
async def export_advisor_endpoint(payload: ExportAdvisorRequest) -> dict:
    """Run the LLM export-advisor author + return the structured manifest."""
    try:
        return await generate_export_manifest(payload)
    except ExportAdvisorError as exc:
        msg = str(exc)
        if msg.startswith("Unknown recipient"):
            code = status.HTTP_400_BAD_REQUEST
            err = "invalid_input"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            err = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=err, message=msg).model_dump(),
        ) from exc
