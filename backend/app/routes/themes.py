"""Public themes endpoint.

The themes table is admin-managed (see ``app.routes.admin.themes`` for
the write surface) but the *list of published themes* is read-public
so the frontend's theme picker can render whatever the design team has
configured — without forcing every chat / image client to authenticate.

Returns a slim projection: slug, display_name, description, era,
preview_image_keys. The full ``rule_pack`` is intentionally omitted
from the public payload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.repositories.themes import ThemeRepository

router = APIRouter(prefix="/themes", tags=["themes"])


@router.get("")
async def list_themes(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return every currently-published theme as a slim projection.

    Frontend uses this to populate the theme selector in MVP 2 and
    any other surface that lets a user pick a theme. The repository's
    ``list_active`` already filters to ``is_current=true`` and
    ``deleted_at IS NULL``; we additionally constrain to
    ``status='published'`` so drafts / archived themes never leak.
    """
    repo = ThemeRepository(db)
    rows = await repo.list_active(status="published")

    slim = [
        {
            "slug": r["slug"],
            "display_name": r["display_name"],
            "description": r.get("description") or "",
            "era": r.get("era"),
            "preview_image_keys": r.get("preview_image_keys") or [],
            "aliases": r.get("aliases") or [],
        }
        for r in rows
    ]

    return {"themes": slim, "count": len(slim)}
