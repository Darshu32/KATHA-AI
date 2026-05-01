"""Client repository — owner-scoped CRUD over the ``clients`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Client


class ClientRepository:
    """Async repo for :class:`Client`.

    All reads are owner-guarded — the architect who owns the client
    is the only user who sees / modifies it.
    """

    @staticmethod
    async def create(
        session: AsyncSession,
        *,
        primary_user_id: str,
        name: str,
        contact_email: str = "",
        notes: str = "",
    ) -> Client:
        row = Client(
            primary_user_id=primary_user_id,
            name=name,
            contact_email=contact_email or "",
            notes=notes or "",
            status="active",
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        client_id: str,
    ) -> Optional[Client]:
        result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_for_owner(
        session: AsyncSession,
        *,
        client_id: str,
        owner_id: str,
    ) -> Optional[Client]:
        """Owner-guarded fetch — cross-owner reads return None."""
        result = await session.execute(
            select(Client).where(
                Client.id == client_id,
                Client.primary_user_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_owner(
        session: AsyncSession,
        *,
        owner_id: str,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[Client]:
        stmt = select(Client).where(Client.primary_user_id == owner_id)
        if not include_archived:
            stmt = stmt.where(Client.status != "archived")
        stmt = stmt.order_by(Client.name.asc()).limit(
            max(1, min(int(limit), 1000))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def archive(
        session: AsyncSession,
        *,
        client_id: str,
        owner_id: str,
    ) -> Optional[Client]:
        row = await ClientRepository.get_for_owner(
            session, client_id=client_id, owner_id=owner_id,
        )
        if row is None:
            return None
        row.status = "archived"
        await session.flush()
        return row
