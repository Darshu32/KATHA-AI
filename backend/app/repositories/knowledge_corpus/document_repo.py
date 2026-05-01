"""Knowledge document repository — CRUD over ``knowledge_documents``.

Used by the corpus ingester (find / create / update document rows
keyed on ``(jurisdiction, source_id)``) and by the
``list_knowledge_sources`` tool.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import KnowledgeDocument


class KnowledgeDocumentRepository:
    """Async repo for :class:`KnowledgeDocument`."""

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        document_id: str,
    ) -> Optional[KnowledgeDocument]:
        result = await session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def find_by_logical_key(
        session: AsyncSession,
        *,
        jurisdiction: str,
        title: str,
        edition: str = "",
    ) -> Optional[KnowledgeDocument]:
        """Look up a document by its (jurisdiction, title, edition) tuple.

        Used by the ingester to decide replace vs create. We don't
        unique-index this combo at the DB layer — different editions
        of NBC live as separate rows — but the ingester treats it as
        a logical key.
        """
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.jurisdiction == jurisdiction,
            KnowledgeDocument.title == title,
            KnowledgeDocument.edition == (edition or ""),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        jurisdiction: str,
        title: str,
        source_type: str,
        publisher: str = "",
        edition: str = "",
        total_pages: int = 0,
        language: str = "en",
        effective_from: Optional[str] = None,
        effective_to: Optional[str] = None,
        storage_key: str = "",
    ) -> KnowledgeDocument:
        """Find-or-create the document by ``(jurisdiction, title, edition)``.

        Existing rows have their metadata updated in place. Chunks
        cascade-delete on re-ingestion via the FK from
        ``knowledge_chunks`` so the caller can wipe + insert.
        """
        existing = await KnowledgeDocumentRepository.find_by_logical_key(
            session,
            jurisdiction=jurisdiction,
            title=title,
            edition=edition,
        )
        if existing is not None:
            existing.source_type = source_type
            existing.publisher = publisher
            existing.total_pages = total_pages
            existing.language = language
            existing.effective_from = effective_from
            existing.effective_to = effective_to
            existing.storage_key = storage_key or existing.storage_key
            existing.status = "processing"
            await session.flush()
            return existing

        doc = KnowledgeDocument(
            title=title,
            source_type=source_type,
            storage_key=storage_key,
            status="processing",
            jurisdiction=jurisdiction,
            publisher=publisher,
            edition=edition,
            total_pages=total_pages,
            language=language,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        session.add(doc)
        await session.flush()
        return doc

    @staticmethod
    async def mark_status(
        session: AsyncSession,
        *,
        document_id: str,
        status: str,
    ) -> Optional[KnowledgeDocument]:
        """Update the status flag (pending / processing / indexed / error)."""
        doc = await KnowledgeDocumentRepository.get_by_id(session, document_id)
        if doc is None:
            return None
        doc.status = status
        await session.flush()
        return doc

    @staticmethod
    async def list_documents(
        session: AsyncSession,
        *,
        jurisdiction: Optional[str] = None,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> list[KnowledgeDocument]:
        """List documents — optional filters on jurisdiction / source_type / status."""
        stmt = select(KnowledgeDocument)
        if jurisdiction is not None:
            stmt = stmt.where(KnowledgeDocument.jurisdiction == jurisdiction)
        if source_type is not None:
            stmt = stmt.where(KnowledgeDocument.source_type == source_type)
        if status is not None:
            stmt = stmt.where(KnowledgeDocument.status == status)
        stmt = stmt.order_by(KnowledgeDocument.title.asc()).limit(
            max(1, min(int(limit), 1000))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count(
        session: AsyncSession,
        *,
        jurisdiction: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(KnowledgeDocument.id))
        if jurisdiction is not None:
            stmt = stmt.where(KnowledgeDocument.jurisdiction == jurisdiction)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)
