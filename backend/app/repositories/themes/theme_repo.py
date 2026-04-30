"""Theme repository — versioned reads, alias resolution, cloning, publishing.

Same pattern as Stage 1 pricing repos:
  - ``list_active`` — every published current-version theme.
  - ``get_active_by_slug`` — alias-aware lookup.
  - ``history_for_slug`` — full version history (including deleted).
  - ``update_rule_pack`` — append a new version (Stage-0 ``create_versioned``).
  - ``clone_theme`` — fresh logical record copying rule pack + aliases.
  - ``publish`` / ``unpublish`` — status transitions, also versioned.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_, select

from app.db import BaseRepository
from app.models.themes import Theme


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _theme_to_dict(row: Theme) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "display_name": row.display_name,
        "era": row.era,
        "description": row.description,
        "status": row.status,
        "rule_pack": dict(row.rule_pack or {}),
        "aliases": list(row.aliases) if row.aliases else None,
        "cloned_from_slug": row.cloned_from_slug,
        "preview_image_keys": (
            list(row.preview_image_keys) if row.preview_image_keys else None
        ),
        "version": row.version,
        "is_current": row.is_current,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": row.source,
        "source_ref": row.source_ref,
    }


class ThemeRepository(BaseRepository[Theme]):
    model = Theme

    # ── Reads ──────────────────────────────────────────────────────

    async def list_active(
        self,
        *,
        status: str | None = "published",
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Active rows (default: published only).

        Pass ``status=None`` to include drafts/archived (admin views).
        """
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when)
        if status is not None:
            stmt = stmt.where(Theme.status == status)
        stmt = stmt.order_by(Theme.display_name)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_theme_to_dict(r) for r in rows]

    async def get_active_by_slug(
        self,
        slug_or_alias: str,
        *,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        """Resolve ``slug_or_alias`` to the active theme row.

        Matches the canonical ``slug`` first, then any alias listed in
        the row's ``aliases`` array. Returns the published row only;
        drafts are not surfaced to non-admin callers (they get the
        previous published version, if any).
        """
        if not slug_or_alias:
            return None
        key = _normalize(slug_or_alias)
        when = when or datetime.now(timezone.utc)
        stmt = (
            self._active_at(when)
            .where(
                or_(Theme.slug == key, Theme.aliases.any(key)),
                Theme.status == "published",
            )
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _theme_to_dict(row) if row else None

    async def get_active_by_slug_admin(
        self,
        slug_or_alias: str,
        *,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        """Admin variant — surfaces drafts too."""
        if not slug_or_alias:
            return None
        key = _normalize(slug_or_alias)
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            or_(Theme.slug == key, Theme.aliases.any(key))
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return _theme_to_dict(row) if row else None

    async def history_for_slug(self, slug: str) -> list[dict[str, Any]]:
        stmt = (
            select(Theme)
            .where(Theme.slug == slug)
            .order_by(Theme.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_theme_to_dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────

    async def update_rule_pack(
        self,
        *,
        slug: str,
        new_rule_pack: dict[str, Any],
        new_display_name: str | None = None,
        new_description: str | None = None,
        new_aliases: list[str] | None = None,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a new version with an updated rule pack.

        Pass ``new_display_name`` / ``new_description`` / ``new_aliases``
        to update those columns alongside; leave them ``None`` to inherit
        from the previous version.
        """
        previous = (
            await self.session.execute(
                self._current_select().where(Theme.slug == slug)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current Theme for slug={slug!r}")

        changes: dict[str, Any] = {"rule_pack": new_rule_pack}
        if new_display_name is not None:
            changes["display_name"] = new_display_name
        if new_description is not None:
            changes["description"] = new_description
        if new_aliases is not None:
            changes["aliases"] = new_aliases
        # NB: status, cloned_from_slug, preview_image_keys are inherited
        # unchanged via BaseRepository.create_versioned.

        new_row = await self.create_versioned(
            previous,
            changes,
            actor_id=actor_id,
            reason=reason or "rule_pack update",
            request_id=request_id,
        )
        return _theme_to_dict(new_row)

    async def update_status(
        self,
        *,
        slug: str,
        new_status: str,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Transition a theme through draft / published / archived.

        Status is versioned — the previous status row is preserved so
        the audit trail is intact.
        """
        if new_status not in {"draft", "published", "archived"}:
            raise ValueError(f"Invalid status: {new_status!r}")
        previous = (
            await self.session.execute(
                self._current_select().where(Theme.slug == slug)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current Theme for slug={slug!r}")

        new_row = await self.create_versioned(
            previous,
            {"status": new_status},
            actor_id=actor_id,
            reason=reason or f"status → {new_status}",
            request_id=request_id,
        )
        return _theme_to_dict(new_row)

    async def clone_theme(
        self,
        *,
        source_slug: str,
        new_slug: str,
        new_display_name: str,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a brand-new theme from an existing one.

        The new theme is its own logical record (``version=1``,
        ``cloned_from_slug=<source>``). The source theme is unchanged.
        Cloned themes start in ``draft`` status — designers iterate
        before publishing.
        """
        new_slug = _normalize(new_slug)
        source = await self.get_active_by_slug_admin(source_slug)
        if source is None:
            raise LookupError(f"No theme to clone from: slug={source_slug!r}")

        # Refuse if a current row already exists for the new slug.
        existing = (
            await self.session.execute(
                self._current_select().where(Theme.slug == new_slug)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(
                f"Cannot clone: a current theme already exists with slug={new_slug!r}"
            )

        return await self._create_brand_new(
            slug=new_slug,
            display_name=new_display_name,
            era=source.get("era"),
            description=f"Cloned from {source['slug']}",
            rule_pack=dict(source["rule_pack"]),
            aliases=None,
            cloned_from_slug=source["slug"],
            status="draft",
            actor_id=actor_id,
            reason=reason or f"clone of {source_slug}",
            request_id=request_id,
        )

    async def _create_brand_new(
        self,
        *,
        slug: str,
        display_name: str,
        era: str | None,
        description: str | None,
        rule_pack: dict[str, Any],
        aliases: list[str] | None,
        cloned_from_slug: str | None,
        status: str,
        actor_id: str | None,
        reason: str | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        """Create a brand-new logical record (``version=1``).

        Used by :meth:`clone_theme`; can be called directly by an admin
        endpoint that creates a theme from scratch (Stage 4+ UI).
        """
        new_row = await self.create(
            {
                "slug": slug,
                "display_name": display_name,
                "era": era,
                "description": description,
                "status": status,
                "rule_pack": rule_pack,
                "aliases": aliases,
                "cloned_from_slug": cloned_from_slug,
                "source": "admin",
            },
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return _theme_to_dict(new_row)
