"""Parametric design route (BRD Layer 2A).

POST /parametric/design — runs the LLM-driven parametric design pipeline:
  validated request → theme + BRD knowledge injection → live LLM call →
  validation against the same theme rule pack → structured spec response.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.knowledge import themes
from app.models.schemas import ErrorResponse
from app.services.parametric_design_service import (
    ParametricDesignError,
    ParametricDesignRequest,
    build_parametric_knowledge,
    generate_parametric_design,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parametric", tags=["parametric"])


@router.get("/themes")
async def list_themes() -> dict:
    """Expose the parametric theme catalogue dynamically — no hardcoded list."""
    return {
        "themes": [
            {
                "key": key,
                "display_name": pack.get("display_name"),
                "era": pack.get("era"),
                "primary_materials": pack.get("material_palette", {}).get("primary", []),
                "signature_moves": pack.get("signature_moves", []),
            }
            for key, pack in (
                (k, themes.get(k)) for k in themes.list_names()
            )
            if pack is not None
        ]
    }


@router.post("/knowledge")
async def parametric_knowledge(payload: ParametricDesignRequest) -> dict:
    """Return only the injected knowledge slice for a (theme, piece) pair.

    Useful for the UI to preview what the LLM will see before running
    the more expensive generation call.
    """
    knowledge = build_parametric_knowledge(payload)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="unknown_theme",
                message=f"No parametric rule pack for theme '{payload.theme}'.",
            ).model_dump(),
        )
    return {
        "theme": payload.theme,
        "piece": {"category": payload.piece_category, "item": payload.piece_item},
        "knowledge": knowledge,
    }


@router.post("/design")
async def parametric_design(payload: ParametricDesignRequest) -> dict:
    """Run the parametric design LLM pipeline."""
    try:
        return await generate_parametric_design(payload)
    except ParametricDesignError as exc:
        # 503 when LLM unavailable, 400 when theme is unknown / inputs unusable.
        msg = str(exc)
        if "Unknown theme" in msg or "no parametric rule pack" in msg.lower():
            code = status.HTTP_400_BAD_REQUEST
            error_key = "invalid_theme"
        else:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
            error_key = "llm_unavailable"
        raise HTTPException(
            status_code=code,
            detail=ErrorResponse(error=error_key, message=msg).model_dump(),
        ) from exc
