"""Diagram generation routes (BRD Layer 2B).

Each diagram type follows the project contract:
  validated request → injected knowledge → live LLM call → deterministic
  renderer using the LLM spec → annotated SVG + structured spec.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.knowledge import themes
from app.models.schemas import ErrorResponse
from app.services.concept_diagram_service import (
    ConceptDiagramError,
    ConceptDiagramRequest,
    build_concept_knowledge,
    generate_concept_diagram,
)
from app.services.form_diagram_service import (
    FormDiagramError,
    FormDiagramRequest,
    build_form_knowledge,
    generate_form_diagram,
)
from app.services.design_process_diagram_service import (
    DesignProcessError,
    DesignProcessRequest,
    build_process_knowledge,
    generate_design_process_diagram,
)
from app.services.solid_void_diagram_service import (
    SolidVoidError,
    SolidVoidRequest,
    build_solid_void_knowledge,
    generate_solid_void_diagram,
)
from app.services.hierarchy_diagram_service import (
    HierarchyError,
    HierarchyRequest,
    build_hierarchy_knowledge,
    generate_hierarchy_diagram,
)
from app.services.spatial_organism_diagram_service import (
    SpatialOrganismError,
    SpatialOrganismRequest,
    build_organism_knowledge,
    generate_spatial_organism_diagram,
)
from app.services.volumetric_block_diagram_service import (
    VolumetricBlockError,
    VolumetricBlockRequest,
    build_block_knowledge,
    generate_volumetric_block_diagram,
)
from app.services.volumetric_diagram_service import (
    VolumetricDiagramError,
    VolumetricDiagramRequest,
    build_volumetric_knowledge,
    generate_volumetric_diagram,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("/types")
async def list_diagram_types() -> dict:
    """Dynamic catalogue — no hardcoded list."""
    return {
        "diagrams": [
            {
                "id": "concept_transparency",
                "name": "Concept Transparency",
                "stage": "BRD 2B #1",
                "summary": "Core design intent — material/form relationship, functional zones, signature moves.",
            },
            {
                "id": "form_development",
                "name": "Form Development",
                "stage": "BRD 2B #2",
                "summary": "Four-stage evolution — volume → grid → subtract → articulate, with theme signature moves.",
            },
            {
                "id": "volumetric_hierarchy",
                "name": "Volumetric Hierarchy",
                "stage": "BRD 2B #3",
                "summary": "Vertical × horizontal reading — silhouette, weight distribution, space allocation, stacking logic.",
            },
            {
                "id": "volumetric_block",
                "name": "Volumetric Diagram",
                "stage": "BRD 2B #4",
                "summary": "3D block read — masses, voids, spatial relationships, slicing strategy.",
            },
            {
                "id": "design_process",
                "name": "Design Process",
                "stage": "BRD 2B #5",
                "summary": "Step-by-step design narrative — decision points, rule drivers, rejected alternatives.",
            },
            {
                "id": "solid_void",
                "name": "Solid vs Void",
                "stage": "BRD 2B #6",
                "summary": "Positive/negative space — solid % / void %, weight pattern, breathing room, watch-outs.",
            },
            {
                "id": "spatial_organism",
                "name": "Spatial Organism",
                "stage": "BRD 2B #7",
                "summary": "How a body inhabits the space — interaction touchpoints, movement choreography, usage pattern.",
            },
            {
                "id": "hierarchy",
                "name": "Hierarchy",
                "stage": "BRD 2B #8",
                "summary": "Three rankings — visual, material, functional — with emphasis rules per tier.",
            },
        ]
    }


@router.post("/concept-transparency/knowledge")
async def concept_knowledge(payload: ConceptDiagramRequest) -> dict:
    """Preview the knowledge slice the LLM will see — no model call."""
    knowledge = build_concept_knowledge(payload)
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


@router.post("/concept-transparency")
async def concept_transparency_endpoint(payload: ConceptDiagramRequest) -> dict:
    """Run the LLM concept-author pipeline + render the annotated SVG."""
    try:
        return await generate_concept_diagram(payload)
    except ConceptDiagramError as exc:
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


@router.post("/form-development/knowledge")
async def form_knowledge(payload: FormDiagramRequest) -> dict:
    """Preview the knowledge slice the form-development LLM stage will see."""
    knowledge = build_form_knowledge(payload)
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


@router.post("/form-development")
async def form_development_endpoint(payload: FormDiagramRequest) -> dict:
    """Run the LLM form-author pipeline + render the annotated 4-stage SVG."""
    try:
        return await generate_form_diagram(payload)
    except FormDiagramError as exc:
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


@router.post("/volumetric-hierarchy/knowledge")
async def volumetric_knowledge(payload: VolumetricDiagramRequest) -> dict:
    """Preview the knowledge slice the volumetric LLM stage will see."""
    knowledge = build_volumetric_knowledge(payload)
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


@router.post("/volumetric-hierarchy")
async def volumetric_hierarchy_endpoint(payload: VolumetricDiagramRequest) -> dict:
    """Run the LLM volumetric-author pipeline + render annotated axonometric SVG."""
    try:
        return await generate_volumetric_diagram(payload)
    except VolumetricDiagramError as exc:
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


@router.post("/volumetric/knowledge")
async def volumetric_block_knowledge(payload: VolumetricBlockRequest) -> dict:
    """Preview the knowledge slice the volumetric (block) LLM stage will see."""
    knowledge = build_block_knowledge(payload)
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


@router.post("/volumetric")
async def volumetric_block_endpoint(payload: VolumetricBlockRequest) -> dict:
    """Run the LLM block/void/relationship pipeline + render annotated axo SVG."""
    try:
        return await generate_volumetric_block_diagram(payload)
    except VolumetricBlockError as exc:
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


@router.post("/design-process/knowledge")
async def design_process_knowledge(payload: DesignProcessRequest) -> dict:
    """Preview the knowledge slice the design-process LLM stage will see."""
    knowledge = build_process_knowledge(payload)
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


@router.post("/design-process")
async def design_process_endpoint(payload: DesignProcessRequest) -> dict:
    """Run the LLM design-process narrator pipeline + render annotated flow SVG."""
    try:
        return await generate_design_process_diagram(payload)
    except DesignProcessError as exc:
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


@router.post("/solid-void/knowledge")
async def solid_void_knowledge(payload: SolidVoidRequest) -> dict:
    """Preview the knowledge slice (incl. computed geometry) the LLM will see."""
    knowledge = build_solid_void_knowledge(payload)
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


@router.post("/solid-void")
async def solid_void_endpoint(payload: SolidVoidRequest) -> dict:
    """Run the LLM solid/void interpreter + render annotated plan SVG."""
    try:
        return await generate_solid_void_diagram(payload)
    except SolidVoidError as exc:
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


@router.post("/spatial-organism/knowledge")
async def spatial_organism_knowledge(payload: SpatialOrganismRequest) -> dict:
    """Preview the knowledge slice the spatial-organism LLM stage will see."""
    knowledge = build_organism_knowledge(payload)
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


@router.post("/spatial-organism")
async def spatial_organism_endpoint(payload: SpatialOrganismRequest) -> dict:
    """Run the LLM body-in-space interpreter + render annotated plan SVG."""
    try:
        return await generate_spatial_organism_diagram(payload)
    except SpatialOrganismError as exc:
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


@router.post("/hierarchy/knowledge")
async def hierarchy_knowledge(payload: HierarchyRequest) -> dict:
    """Preview the knowledge slice the hierarchy LLM stage will see."""
    knowledge = build_hierarchy_knowledge(payload)
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


@router.post("/hierarchy")
async def hierarchy_endpoint(payload: HierarchyRequest) -> dict:
    """Run the LLM three-rank hierarchy author + render annotated SVG."""
    try:
        return await generate_hierarchy_diagram(payload)
    except HierarchyError as exc:
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
