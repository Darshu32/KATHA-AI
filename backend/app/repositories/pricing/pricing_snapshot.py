"""Repository for ``pricing_snapshots`` (immutable append-only)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import PricingSnapshot
from app.repositories.pricing._serialize import pricing_snapshot_to_dict


class PricingSnapshotRepository:
    """Append-only — no versioning, no soft-delete, no updates.

    Doesn't subclass ``BaseRepository`` because most of the inherited
    machinery (versioning, soft-delete) doesn't apply.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads ──────────────────────────────────────────────────────────

    async def get(self, id_: str) -> Optional[dict[str, Any]]:
        row = (
            await self.session.execute(
                select(PricingSnapshot).where(PricingSnapshot.id == id_)
            )
        ).scalar_one_or_none()
        return pricing_snapshot_to_dict(row) if row else None

    async def list_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(PricingSnapshot)
            .where(
                PricingSnapshot.target_type == target_type,
                PricingSnapshot.target_id == target_id,
            )
            .order_by(PricingSnapshot.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [pricing_snapshot_to_dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        target_type: str,
        snapshot_data: dict[str, Any],
        source_versions: dict[str, Any],
        target_id: str | None = None,
        project_id: str | None = None,
        city: str | None = None,
        market_segment: str | None = None,
        actor_id: str | None = None,
        actor_kind: str = "system",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        row = PricingSnapshot(
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            city=city,
            market_segment=market_segment,
            snapshot_data=snapshot_data,
            source_versions=source_versions,
            actor_id=actor_id,
            actor_kind=actor_kind,
            request_id=request_id,
        )
        self.session.add(row)
        await self.session.flush()
        return pricing_snapshot_to_dict(row)
