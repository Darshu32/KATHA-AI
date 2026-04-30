"""Public accessor for the suggestions catalog.

The frontend reads this on every empty-state render — keep it cheap
and fall back to a small built-in default if the DB is unreachable
or empty (fresh dev box pre-seed).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.suggestions import SuggestionRepository


# Last-ditch fallback used when the DB has no published rows for the
# requested context (e.g. a fresh dev DB pre-seed). The backend never
# returns an empty list to the frontend in normal operation; this keeps
# the empty hero usable in degraded environments.
_FALLBACK_CHIPS: list[dict[str, Any]] = [
    {
        "slug": "modern_villa_facade_ideas",
        "label": "Modern villa facade ideas",
        "prompt": (
            "Suggest modern villa facade design ideas with clean lines, "
            "large glass panels, and natural materials"
        ),
        "weight": 100,
        "tags": ["facade", "modern"],
        "contexts": ["chat_empty_hero"],
        "source": "fallback:hardcoded",
    },
]


async def list_published_suggestions(
    session: AsyncSession,
    *,
    context: Optional[str] = None,
    limit: int = 12,
    when: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Return published chips for a given context.

    - Filters by context (rows with empty ``contexts`` are global).
    - Falls back to a small built-in list if the DB has nothing.
    - Trimmed for the frontend: only label/prompt/weight surface.
    """
    repo = SuggestionRepository(session)
    rows = await repo.list_published(
        context=context, limit=limit, when=when
    )
    if not rows:
        rows = list(_FALLBACK_CHIPS)
    return rows


async def list_published_for_frontend(
    session: AsyncSession,
    *,
    context: Optional[str] = None,
    limit: int = 12,
    when: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Compact projection used by the public ``/suggestions`` endpoint.

    Drops admin-only fields (id, version, source, …) so the response
    is small + cacheable + safe to log.
    """
    rows = await list_published_suggestions(
        session, context=context, limit=limit, when=when
    )
    return [
        {
            "slug": r["slug"],
            "label": r["label"],
            "prompt": r["prompt"],
            "weight": int(r.get("weight", 100)),
            "tags": r.get("tags") or [],
        }
        for r in rows
    ]
