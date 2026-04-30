"""SuggestionRepository — versioned, context-filtered chip lookups.

Read methods
------------
- ``list_published`` — current rows visible on the public endpoint;
  optionally filter by ``context``.
- ``list_admin``     — admin-side, includes drafts + archived.
- ``get_by_slug``    — exact lookup, with admin/public toggle.
- ``history_for``    — every version (incl. soft-deleted).

Write methods
-------------
- ``update``         — append a new version (label/prompt/contexts/weight/tags).
- ``update_status``  — draft / published / archived transition.
- ``create``         — brand-new logical record (Stage 4+ admin UI).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.suggestions import Suggestion


def _to_dict(row: Suggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "label": row.label,
        "prompt": row.prompt,
        "description": row.description,
        "contexts": list(row.contexts) if row.contexts else [],
        "weight": int(row.weight),
        "status": row.status,
        "tags": list(row.tags) if row.tags else None,
        "version": row.version,
        "is_current": row.is_current,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": row.source,
    }


class SuggestionRepository(BaseRepository[Suggestion]):
    model = Suggestion

    # ── Reads ─────────────────────────────────────────────────────

    async def list_published(
        self,
        *,
        context: Optional[str] = None,
        limit: int = 12,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Active + published, optionally filtered by context.

        Order: ``weight DESC, slug ASC``. Empty ``contexts`` array on a
        row means "global" — those chips surface in every context.
        """
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(Suggestion.status == "published")
        if context:
            # Either context match OR global (empty contexts array).
            from sqlalchemy import or_
            stmt = stmt.where(
                or_(
                    Suggestion.contexts.any(context),
                    Suggestion.contexts == [],
                )
            )
        stmt = stmt.order_by(Suggestion.weight.desc(), Suggestion.slug)
        stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def list_admin(
        self,
        *,
        status: Optional[str] = None,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when)
        if status is not None:
            stmt = stmt.where(Suggestion.status == status)
        stmt = stmt.order_by(Suggestion.weight.desc(), Suggestion.slug)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    async def get_by_slug(
        self,
        slug: str,
        *,
        published_only: bool = True,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(Suggestion.slug == slug)
        if published_only:
            stmt = stmt.where(Suggestion.status == "published")
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _to_dict(row) if row else None

    async def history_for(self, slug: str) -> list[dict[str, Any]]:
        stmt = (
            select(Suggestion)
            .where(Suggestion.slug == slug)
            .order_by(Suggestion.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_to_dict(r) for r in rows]

    # ── Writes ────────────────────────────────────────────────────

    async def update(
        self,
        *,
        slug: str,
        label: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        contexts: Optional[list[str]] = None,
        weight: Optional[int] = None,
        tags: Optional[list[str]] = None,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        previous = (
            await self.session.execute(
                self._current_select().where(Suggestion.slug == slug)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current Suggestion for slug={slug!r}")

        changes: dict[str, Any] = {}
        if label is not None:
            changes["label"] = label
        if prompt is not None:
            changes["prompt"] = prompt
        if description is not None:
            changes["description"] = description
        if contexts is not None:
            changes["contexts"] = contexts
        if weight is not None:
            if not 0 <= int(weight) <= 1000:
                raise ValueError("weight must be in [0, 1000]")
            changes["weight"] = int(weight)
        if tags is not None:
            changes["tags"] = tags

        if not changes:
            raise ValueError("update() called with no changes")

        new_row = await self.create_versioned(
            previous,
            changes,
            actor_id=actor_id,
            reason=reason or "suggestion update",
            request_id=request_id,
        )
        return _to_dict(new_row)

    async def update_status(
        self,
        *,
        slug: str,
        new_status: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if new_status not in {"draft", "published", "archived"}:
            raise ValueError(f"Invalid status: {new_status!r}")
        previous = (
            await self.session.execute(
                self._current_select().where(Suggestion.slug == slug)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current Suggestion for slug={slug!r}")

        new_row = await self.create_versioned(
            previous,
            {"status": new_status},
            actor_id=actor_id,
            reason=reason or f"status → {new_status}",
            request_id=request_id,
        )
        return _to_dict(new_row)

    async def create_new(
        self,
        *,
        slug: str,
        label: str,
        prompt: str,
        contexts: Optional[list[str]] = None,
        weight: int = 100,
        status: str = "draft",
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if status not in {"draft", "published", "archived"}:
            raise ValueError(f"Invalid status: {status!r}")
        if not 0 <= int(weight) <= 1000:
            raise ValueError("weight must be in [0, 1000]")
        # Refuse if a current row already exists.
        existing = (
            await self.session.execute(
                self._current_select().where(Suggestion.slug == slug)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(
                f"Suggestion with slug={slug!r} already exists (current version v{existing.version})"
            )

        new_row = await self.create(
            {
                "slug": slug,
                "label": label,
                "prompt": prompt,
                "description": description,
                "contexts": contexts or [],
                "weight": int(weight),
                "status": status,
                "tags": tags,
                "source": "admin",
            },
            actor_id=actor_id,
            reason=reason or f"create suggestion {slug}",
            request_id=request_id,
        )
        return _to_dict(new_row)
