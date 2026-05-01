"""Upload repository — CRUD + owner-scoped queries over uploaded_assets."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import UploadedAsset


class UploadRepository:
    """Async repo for :class:`UploadedAsset`.

    Every method takes the caller's :class:`AsyncSession` and flushes
    without committing. The owner-scoped lookups are how the route
    layer enforces "users only see their own uploads".
    """

    @staticmethod
    async def create(
        session: AsyncSession,
        *,
        owner_id: str,
        kind: str,
        storage_backend: str,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        content_hash: str = "",
        project_id: Optional[str] = None,
        status: str = "uploading",
        metadata: Optional[dict[str, Any]] = None,
    ) -> UploadedAsset:
        row = UploadedAsset(
            owner_id=owner_id,
            project_id=project_id,
            kind=kind or "image",
            storage_backend=storage_backend,
            storage_key=storage_key,
            original_filename=original_filename or "",
            mime_type=mime_type or "application/octet-stream",
            size_bytes=int(size_bytes or 0),
            content_hash=content_hash or "",
            status=status,
            metadata_=dict(metadata or {}),
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def mark_status(
        session: AsyncSession,
        *,
        asset_id: str,
        status: str,
        error_message: str = "",
    ) -> Optional[UploadedAsset]:
        row = await UploadRepository.get_by_id(session, asset_id=asset_id)
        if row is None:
            return None
        row.status = status
        if error_message:
            row.error_message = error_message
        await session.flush()
        return row

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        *,
        asset_id: str,
    ) -> Optional[UploadedAsset]:
        result = await session.execute(
            select(UploadedAsset).where(UploadedAsset.id == asset_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_for_owner(
        session: AsyncSession,
        *,
        asset_id: str,
        owner_id: str,
    ) -> Optional[UploadedAsset]:
        """Owner-guarded fetch.

        Routes / agent tools call this to enforce "users only see
        their own uploads". Mismatched owner returns ``None`` —
        we don't leak existence.
        """
        result = await session.execute(
            select(UploadedAsset).where(
                UploadedAsset.id == asset_id,
                UploadedAsset.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_owner(
        session: AsyncSession,
        *,
        owner_id: str,
        project_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[UploadedAsset]:
        stmt = select(UploadedAsset).where(UploadedAsset.owner_id == owner_id)
        if project_id is not None:
            stmt = stmt.where(UploadedAsset.project_id == project_id)
        if kind is not None:
            stmt = stmt.where(UploadedAsset.kind == kind)
        if status is not None:
            stmt = stmt.where(UploadedAsset.status == status)
        stmt = stmt.order_by(UploadedAsset.created_at.desc()).limit(
            max(1, min(int(limit), 500))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete_for_owner(
        session: AsyncSession,
        *,
        asset_id: str,
        owner_id: str,
    ) -> Optional[UploadedAsset]:
        """Delete the row, owner-guarded. Returns the removed row so
        the route can also clean up storage. ``None`` when not found
        or owned by someone else."""
        row = await UploadRepository.get_for_owner(
            session, asset_id=asset_id, owner_id=owner_id,
        )
        if row is None:
            return None
        await session.delete(row)
        await session.flush()
        return row

    @staticmethod
    async def count_for_owner(
        session: AsyncSession,
        *,
        owner_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(UploadedAsset.id)).where(
                UploadedAsset.owner_id == owner_id,
            )
        )
        return int(result.scalar_one() or 0)
