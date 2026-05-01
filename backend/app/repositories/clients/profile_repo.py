"""Client-profile repository — one row per client, refreshed by extractor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ClientProfile


class ClientProfileRepository:
    """Async repo for :class:`ClientProfile`.

    The extractor writes here — find-or-create via :meth:`upsert`.
    Tools read with :meth:`get_for_client`.
    """

    @staticmethod
    async def get_for_client(
        session: AsyncSession,
        *,
        client_id: str,
    ) -> Optional[ClientProfile]:
        result = await session.execute(
            select(ClientProfile).where(ClientProfile.client_id == client_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        client_id: str,
        project_count: int,
        typical_budget_inr: dict[str, Any],
        recurring_room_types: list[Any],
        recurring_themes: list[Any],
        accessibility_flags: list[Any],
        constraints: list[Any],
        last_project_at: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> ClientProfile:
        existing = await ClientProfileRepository.get_for_client(
            session, client_id=client_id,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing is not None:
            existing.project_count = int(project_count or 0)
            existing.typical_budget_inr = dict(typical_budget_inr or {})
            existing.recurring_room_types = list(recurring_room_types or [])
            existing.recurring_themes = list(recurring_themes or [])
            existing.accessibility_flags = list(accessibility_flags or [])
            existing.constraints = list(constraints or [])
            existing.last_project_at = last_project_at
            existing.last_extracted_at = now_iso
            if extra is not None:
                existing.extra = dict(extra)
            await session.flush()
            return existing

        row = ClientProfile(
            client_id=client_id,
            project_count=int(project_count or 0),
            typical_budget_inr=dict(typical_budget_inr or {}),
            recurring_room_types=list(recurring_room_types or []),
            recurring_themes=list(recurring_themes or []),
            accessibility_flags=list(accessibility_flags or []),
            constraints=list(constraints or []),
            last_project_at=last_project_at,
            last_extracted_at=now_iso,
            extra=dict(extra or {}),
        )
        session.add(row)
        await session.flush()
        return row
