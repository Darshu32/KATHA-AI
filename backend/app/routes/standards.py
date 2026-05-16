"""Public building-standards endpoint (BRD §1B / §4.2).

The ``building_standards`` table (Stage 3B) is admin-managed
(see ``app.routes.admin.standards`` for the write surface) but the
catalogue itself is read-public so the frontend can:

- Show "applicable standards" badges on the design canvas
- Render the Problems-tab citation chips
- Power dropdowns / cheatsheets in the chat workspace

Returns a slim projection that intentionally omits internal columns
(version, deleted_at, created_by). Frontend only needs slug,
display_name, segment, the constrained numeric fields, and the
source citation.

NOT a substitute for ``/projects/{id}/validate`` — that endpoint
runs the live validator against a stored design graph. This one is
a *catalogue* (what rules exist), not an *audit* (whether a design
breaks them).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.standards.knowledge_service import list_standards_by_category

router = APIRouter(prefix="/standards", tags=["standards"])


# Public projection — drop internal columns that callers don't need.
_PUBLIC_FIELDS = (
    "slug",
    "category",
    "subcategory",
    "jurisdiction",
    "display_name",
    "notes",
    "data",
    "source_section",
    "source_doc",
)


# Friendly segment → subcategory mapping. Frontend uses the segment
# keyword the BRD speaks ("residential" / "commercial" / "hospitality"),
# the DB uses ``residential_room`` etc.
_SEGMENT_TO_SUBCATEGORY: dict[str, str] = {
    "residential": "residential_room",
    "commercial": "commercial_room",
    "hospitality": "hospitality_room",
}


def _project(row: dict) -> dict:
    return {k: row.get(k) for k in _PUBLIC_FIELDS}


@router.get("")
async def list_standards(
    category: str = Query(
        default="space",
        description="space | clearance | mep | code | ergonomics | manufacturing",
    ),
    segment: Optional[str] = Query(
        default=None,
        description=(
            "Only when category=space. One of residential / commercial / "
            "hospitality. Maps to the DB subcategory."
        ),
    ),
    jurisdiction: str = Query(default="india_nbc"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List authoritative standards from the ``building_standards``
    table — DB-backed, jurisdiction-aware, citation-carrying.

    Examples
    --------
    - ``/standards?category=space&segment=residential`` → bedroom,
      kitchen, bathroom, … with min/typical areas and the NBC clause
      that defines each minimum.
    - ``/standards?category=clearance`` → door / corridor / stair
      width minimums.
    """
    rows = await list_standards_by_category(
        db, category=category, jurisdiction=jurisdiction
    )

    if category == "space" and segment:
        subcat = _SEGMENT_TO_SUBCATEGORY.get(segment.lower())
        if subcat is not None:
            rows = [r for r in rows if r.get("subcategory") == subcat]

    return {
        "standards": [_project(r) for r in rows],
        "count": len(rows),
        "filter": {
            "category": category,
            "segment": segment,
            "jurisdiction": jurisdiction,
        },
    }
