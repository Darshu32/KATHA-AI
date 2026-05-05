"""Public project-types endpoint.

Serves the canonical list defined in ``app.services.project_types`` so
the frontend renders one source of truth instead of duplicating
constants. The list is small (9 items today), changes rarely, and
contains no per-user data — so it's an unauthenticated GET with
trivially long cacheability.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.project_types import (
    PROJECT_TYPE_DEFINITIONS,
    list_definitions,
)

router = APIRouter(prefix="/project-types", tags=["project-types"])


@router.get("")
async def list_project_types() -> dict:
    """Return every project type definition with display data.

    Each entry contains:
      - ``slug``           : enum value (e.g. ``residential``)
      - ``label``          : UI label
      - ``description``    : one-line summary
      - ``starter_prompts``: starter prompts for the canvas empty state
      - ``visual_hint``    : (informational) prefix used in image-gen
      - ``is_primary``     : whether this surfaces as a primary button
      - ``sort_order``     : ascending sort

    No auth, no body. Frontend is expected to fetch this once at app
    boot (or per-route mount) and cache for the session.
    """
    return {
        "project_types": list_definitions(),
        "count": len(PROJECT_TYPE_DEFINITIONS),
    }
