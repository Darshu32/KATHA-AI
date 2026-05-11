"""Notes repository — CRUD for the ``note_sections`` table.

Phase 1 of the Notes feature gives every chat conversation its own
notebook. A notebook is *implicit* — the set of all sections sharing a
``conversation_id`` for a given ``owner_id``. There is no parent
``notebooks`` table.

Convention (matches ``chat_history.chat_repo``)
-----------------------------------------------
- All methods take an :class:`AsyncSession` from the caller.
- We ``flush()`` but never ``commit()`` — the dependency wrapper in
  ``app.database.get_db`` owns the transaction boundary.
- Ownership is enforced on every read and write: a user can never
  touch another user's note rows even if they guess an ID.

Why upsert (PUT) instead of separate POST + PATCH
-------------------------------------------------
The frontend mints section IDs locally so optimistic UI works
without a server round-trip. The same ID is then synced via PUT —
create on first call, update on every subsequent call. Two endpoints
would buy nothing and complicate the debounce / retry logic.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import NoteSection


class NotesRepository:
    """Async repo for ``note_sections``."""

    # ────────────────────────────────────────────────────────────────
    # Reads
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def list_for_conversation(
        session: AsyncSession,
        *,
        owner_id: str,
        conversation_id: str,
    ) -> list[NoteSection]:
        """All sections in one conversation's notebook.

        Sorted newest-first by ``created_at`` so the UI matches the
        existing localStorage behaviour (latest section on top).
        """
        result = await session.execute(
            select(NoteSection)
            .where(
                NoteSection.owner_id == owner_id,
                NoteSection.conversation_id == conversation_id,
            )
            .order_by(NoteSection.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all_for_owner(
        session: AsyncSession,
        *,
        owner_id: str,
        limit: int = 500,
    ) -> list[NoteSection]:
        """Every section owned by a user, across all conversations.

        Used by the migration-push flow to dedupe before importing.
        ``limit`` is generous — most users will be far below 500.
        """
        result = await session.execute(
            select(NoteSection)
            .where(NoteSection.owner_id == owner_id)
            .order_by(NoteSection.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id_for_owner(
        session: AsyncSession,
        *,
        section_id: str,
        owner_id: str,
    ) -> Optional[NoteSection]:
        """Fetch a section, but only if the owner matches.

        Use this in route handlers to guard against cross-user reads
        when the client supplies an ID.
        """
        result = await session.execute(
            select(NoteSection).where(
                NoteSection.id == section_id,
                NoteSection.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    # ────────────────────────────────────────────────────────────────
    # Writes
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def upsert(
        session: AsyncSession,
        *,
        section_id: str,
        owner_id: str,
        conversation_id: str,
        title: str,
        blocks: list[dict[str, Any]],
        tags: list[str],
        image_url: Optional[str] = None,
        source_message_id: Optional[str] = None,
        client_created_at: Optional[str] = None,
    ) -> NoteSection:
        """Create-or-update a section by client-supplied ID.

        - If no row exists for ``section_id``, insert a new one owned
          by ``owner_id``.
        - If a row exists AND it belongs to ``owner_id``, update it.
        - If a row exists but belongs to *another* owner, return that
          row's owner unchanged via the caller's None-check (we don't
          flip ownership). The route layer treats this as 404 to avoid
          leaking the existence of another user's section.
        """
        existing = await session.execute(
            select(NoteSection).where(NoteSection.id == section_id)
        )
        row = existing.scalar_one_or_none()

        if row is None:
            row = NoteSection(
                id=section_id,
                owner_id=owner_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                title=title,
                blocks=blocks,
                tags=tags,
                image_url=image_url,
                client_created_at=client_created_at,
            )
            session.add(row)
            await session.flush()
            return row

        if row.owner_id != owner_id:
            # Caller will surface a 404 — don't reveal that the ID
            # exists under another account.
            return None  # type: ignore[return-value]

        # Update mutable fields. ``conversation_id`` is *not* mutable
        # post-creation: a section belongs to the conversation it was
        # born in. If a user wants the same content elsewhere, they
        # create a new section.
        row.title = title
        row.blocks = blocks
        row.tags = tags
        # ``image_url`` is overwritable — explicit None clears it
        # (user removed the image). Always assigning is correct.
        row.image_url = image_url
        if source_message_id is not None:
            row.source_message_id = source_message_id
        if client_created_at is not None:
            row.client_created_at = client_created_at
        await session.flush()
        return row

    @staticmethod
    async def import_skip_existing(
        session: AsyncSession,
        *,
        owner_id: str,
        sections: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Bulk-insert sections, skipping any IDs that already exist.

        Used for the one-time localStorage → server migration on first
        login. We *skip* rather than overwrite: if the user already has
        a server-side version of a section, the server's copy wins
        (it's been touched more recently than a stale localStorage
        snapshot from another device).

        Returns ``(imported, skipped)``.
        """
        if not sections:
            return (0, 0)

        ids = [s["id"] for s in sections if s.get("id")]
        if not ids:
            return (0, 0)

        existing_rows = await session.execute(
            select(NoteSection.id).where(NoteSection.id.in_(ids))
        )
        existing_ids = {row[0] for row in existing_rows.all()}

        imported = 0
        skipped = 0
        for s in sections:
            sid = s.get("id")
            if not sid or sid in existing_ids:
                skipped += 1
                continue
            session.add(
                NoteSection(
                    id=sid,
                    owner_id=owner_id,
                    conversation_id=s["conversation_id"],
                    source_message_id=s.get("source_message_id"),
                    title=s.get("title") or "Notes",
                    blocks=s.get("blocks") or [],
                    tags=s.get("tags") or [],
                    image_url=s.get("image_url"),
                    client_created_at=s.get("client_created_at"),
                )
            )
            imported += 1

        if imported:
            await session.flush()
        return (imported, skipped)

    @staticmethod
    async def delete_by_id_for_owner(
        session: AsyncSession,
        *,
        section_id: str,
        owner_id: str,
    ) -> bool:
        """Delete a section. Returns True if a row was actually removed.

        The ``owner_id`` predicate is the security boundary — never
        delete by ID alone.
        """
        result = await session.execute(
            delete(NoteSection).where(
                NoteSection.id == section_id,
                NoteSection.owner_id == owner_id,
            )
        )
        await session.flush()
        return (result.rowcount or 0) > 0
