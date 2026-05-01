"""Architect-profile repository — one row per user, refreshed nightly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ArchitectProfile


class ArchitectProfileRepository:
    """Async repo for :class:`ArchitectProfile`."""

    @staticmethod
    async def get_for_user(
        session: AsyncSession,
        *,
        user_id: str,
    ) -> Optional[ArchitectProfile]:
        result = await session.execute(
            select(ArchitectProfile).where(ArchitectProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        user_id: str,
        project_count: int,
        preferred_themes: list[Any],
        preferred_materials: list[Any],
        preferred_palette_hexes: list[Any],
        typical_room_dimensions_m: dict[str, Any],
        tool_usage: list[Any],
        last_project_at: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> ArchitectProfile:
        existing = await ArchitectProfileRepository.get_for_user(
            session, user_id=user_id,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing is not None:
            existing.project_count = int(project_count or 0)
            existing.preferred_themes = list(preferred_themes or [])
            existing.preferred_materials = list(preferred_materials or [])
            existing.preferred_palette_hexes = list(preferred_palette_hexes or [])
            existing.typical_room_dimensions_m = dict(typical_room_dimensions_m or {})
            existing.tool_usage = list(tool_usage or [])
            existing.last_project_at = last_project_at
            existing.last_extracted_at = now_iso
            if extra is not None:
                existing.extra = dict(extra)
            await session.flush()
            return existing

        row = ArchitectProfile(
            user_id=user_id,
            project_count=int(project_count or 0),
            preferred_themes=list(preferred_themes or []),
            preferred_materials=list(preferred_materials or []),
            preferred_palette_hexes=list(preferred_palette_hexes or []),
            typical_room_dimensions_m=dict(typical_room_dimensions_m or {}),
            tool_usage=list(tool_usage or []),
            last_project_at=last_project_at,
            last_extracted_at=now_iso,
            extra=dict(extra or {}),
        )
        session.add(row)
        await session.flush()
        return row
