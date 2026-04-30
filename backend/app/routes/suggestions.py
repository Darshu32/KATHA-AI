"""Public suggestions endpoint (Stage 3F).

The frontend hits this on every empty-state render, so it's:
  - **anonymous** (no auth)
  - **cacheable** (set ``Cache-Control: public, max-age=60``)
  - **resilient** — service falls back to a built-in chip list if the
    DB has nothing.

Admin writes go through ``/admin/suggestions`` (auth-protected).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.suggestions.knowledge_service import (
    list_published_for_frontend,
)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


@router.get("")
async def list_suggestions(
    response: Response,
    context: Optional[str] = Query(
        default=None,
        description=(
            "Where the chip is shown — e.g. 'chat_empty_hero', "
            "'brief_intake'. Empty returns global chips only."
        ),
    ),
    limit: int = Query(default=12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return published chips for the given context.

    Response body shape::

        {
          "suggestions": [
            {"slug": "...", "label": "...", "prompt": "...", "weight": 100, "tags": [...]},
            ...
          ],
          "context": "chat_empty_hero",
          "count": 4
        }

    The frontend takes the array and renders chips ordered by weight
    DESC (already done server-side).
    """
    rows = await list_published_for_frontend(
        db, context=context, limit=limit
    )
    # 60s public cache — chips don't change often, and we tolerate
    # mild staleness because the fallback list keeps the UX safe.
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "suggestions": rows,
        "context": context,
        "count": len(rows),
    }
