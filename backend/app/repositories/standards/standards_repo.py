"""Building-standards repository — versioned, jurisdiction-aware reads.

Methods
-------
- ``list_active`` — every current row in a (category, jurisdiction).
- ``get_active`` — exact ``(slug, category, jurisdiction)`` lookup.
- ``resolve`` — exact, then fall back to the BRD baseline jurisdiction.
- ``history_for`` — every version of a logical key.
- ``update_data`` — append a new version with updated rule data.

The resolver is what makes Stage 3B *useful*: a project scoped to
``maharashtra_dcr`` gets DCR-specific rules where they exist and the
``india_nbc`` baseline everywhere else, in a single call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.standards import BuildingStandard


_BASELINE_JURISDICTION = "india_nbc"


def _to_dict(row: BuildingStandard) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "category": row.category,
        "jurisdiction": row.jurisdiction,
        "subcategory": row.subcategory,
        "display_name": row.display_name,
        "notes": row.notes,
        "data": dict(row.data or {}),
        "source_section": row.source_section,
        "source_doc": row.source_doc,
        "version": row.version,
        "is_current": row.is_current,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": row.source,
    }


class StandardsRepository(BaseRepository[BuildingStandard]):
    model = BuildingStandard

    # ── Reads ─────────────────────────────────────────────────────

    async def list_active(
        self,
        *,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        jurisdiction: str = _BASELINE_JURISDICTION,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            BuildingStandard.jurisdiction == jurisdiction
        )
        if category is not None:
            stmt = stmt.where(BuildingStandard.category == category)
        if subcategory is not None:
            stmt = stmt.where(BuildingStandard.subcategory == subcategory)
        stmt = stmt.order_by(BuildingStandard.category, BuildingStandard.slug)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get_active(
        self,
        *,
        slug: str,
        category: str,
        jurisdiction: str = _BASELINE_JURISDICTION,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            BuildingStandard.slug == slug,
            BuildingStandard.category == category,
            BuildingStandard.jurisdiction == jurisdiction,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def resolve(
        self,
        *,
        slug: str,
        category: str,
        jurisdiction: str = _BASELINE_JURISDICTION,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        """Pick the most specific available row.

        Lookup order:
          1. Exact ``(slug, category, jurisdiction)``.
          2. Fall back to ``(slug, category, india_nbc)`` baseline.
          3. ``None`` if neither exists.

        This is what callers should use — direct ``get_active`` lookups
        only return jurisdiction-exact rows and miss the baseline.
        """
        exact = await self.get_active(
            slug=slug, category=category, jurisdiction=jurisdiction, when=when
        )
        if exact is not None:
            return exact
        if jurisdiction == _BASELINE_JURISDICTION:
            return None
        return await self.get_active(
            slug=slug,
            category=category,
            jurisdiction=_BASELINE_JURISDICTION,
            when=when,
        )

    async def history_for(
        self,
        *,
        slug: str,
        category: str,
        jurisdiction: str = _BASELINE_JURISDICTION,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(BuildingStandard)
            .where(
                BuildingStandard.slug == slug,
                BuildingStandard.category == category,
                BuildingStandard.jurisdiction == jurisdiction,
            )
            .order_by(BuildingStandard.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    # ── Writes ────────────────────────────────────────────────────

    async def update_data(
        self,
        *,
        slug: str,
        category: str,
        jurisdiction: str = _BASELINE_JURISDICTION,
        new_data: dict[str, Any],
        new_notes: str | None = None,
        new_display_name: str | None = None,
        new_source_section: str | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        previous = (
            await self.session.execute(
                self._current_select().where(
                    BuildingStandard.slug == slug,
                    BuildingStandard.category == category,
                    BuildingStandard.jurisdiction == jurisdiction,
                )
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(
                f"No current BuildingStandard for slug={slug!r} "
                f"category={category!r} jurisdiction={jurisdiction!r}"
            )

        changes: dict[str, Any] = {"data": new_data}
        if new_notes is not None:
            changes["notes"] = new_notes
        if new_display_name is not None:
            changes["display_name"] = new_display_name
        if new_source_section is not None:
            changes["source_section"] = new_source_section

        new_row = await self.create_versioned(
            previous,
            changes,
            actor_id=actor_id,
            reason=reason or "rule update",
            request_id=request_id,
        )
        return _to_dict(new_row)
