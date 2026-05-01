"""Chat history repository — CRUD + listing helpers for chat persistence.

Stage 5 of the agent runtime keeps every conversation turn in DB so:

- The architect can resume a chat across browser sessions.
- The agent loop reads prior turns instead of trusting client-supplied
  history (security: a malicious client could otherwise rewrite the
  past to manipulate the agent).
- The audit / compliance layer has a complete record of what the
  agent told the user.

This repository is the only module that reads / writes the
``chat_sessions`` and ``chat_messages`` tables. Routes and the agent
loop call it; nobody else touches the tables directly.

All methods take an :class:`AsyncSession` from the caller — the
session controls the transaction boundary. Methods flush but never
commit (matching the convention used by every other repository).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ChatMessage, ChatSession


class ChatHistoryRepository:
    """Async repo for ``chat_sessions`` + ``chat_messages``."""

    # ────────────────────────────────────────────────────────────────
    # Sessions
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def create_session(
        session: AsyncSession,
        *,
        owner_id: str,
        project_id: Optional[str] = None,
        title: str = "",
    ) -> ChatSession:
        """Create a new chat session row.

        Caller commits the transaction. ``id`` is populated after the
        flush via the UUIDMixin default factory.
        """
        chat = ChatSession(
            owner_id=owner_id,
            project_id=project_id,
            title=title or "",
            status="active",
            message_count=0,
        )
        session.add(chat)
        await session.flush()
        return chat

    @staticmethod
    async def get_session(
        session: AsyncSession,
        session_id: str,
    ) -> Optional[ChatSession]:
        """Fetch a session by id. Returns None if missing."""
        result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_session_for_owner(
        session: AsyncSession,
        *,
        session_id: str,
        owner_id: str,
    ) -> Optional[ChatSession]:
        """Fetch a session, but only if the owner matches.

        Use this in route handlers — it guards against a user reading /
        writing another user's chat history when the client supplies a
        ``session_id``.
        """
        result = await session.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_sessions_for_owner(
        session: AsyncSession,
        *,
        owner_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
        include_archived: bool = False,
    ) -> list[ChatSession]:
        """List recent sessions for an owner.

        If ``project_id`` is provided, only sessions scoped to that
        project are returned. Otherwise *all* the owner's sessions.
        Sorted newest-first by ``updated_at``.
        """
        stmt = select(ChatSession).where(ChatSession.owner_id == owner_id)
        if project_id is not None:
            stmt = stmt.where(ChatSession.project_id == project_id)
        if not include_archived:
            stmt = stmt.where(ChatSession.status != "archived")
        stmt = stmt.order_by(ChatSession.updated_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def archive_session(
        session: AsyncSession,
        *,
        session_id: str,
        owner_id: str,
    ) -> Optional[ChatSession]:
        """Mark a session as archived. Idempotent. Returns None if missing."""
        chat = await ChatHistoryRepository.get_session_for_owner(
            session,
            session_id=session_id,
            owner_id=owner_id,
        )
        if chat is None:
            return None
        chat.status = "archived"
        await session.flush()
        return chat

    # ────────────────────────────────────────────────────────────────
    # Messages
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def append_message(
        session: AsyncSession,
        *,
        session_id: str,
        role: str,
        content: dict[str, Any],
        text_preview: str = "",
        tool_call_count: int = 0,
        elapsed_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> ChatMessage:
        """Append one message to a session.

        Computes ``position`` server-side (max + 1) so concurrent
        appends from the same session would conflict on the unique
        index — a concession we accept since one chat session has one
        active client at a time.

        Updates the parent ``ChatSession.message_count`` +
        ``last_message_at`` so list views don't have to count rows.

        ``role`` must be one of ``user`` | ``assistant`` | ``tool``.
        Other values are rejected by the DB CHECK constraint.
        """
        # Compute next position.
        result = await session.execute(
            select(func.coalesce(func.max(ChatMessage.position), 0)).where(
                ChatMessage.session_id == session_id
            )
        )
        next_position = int(result.scalar_one()) + 1

        msg = ChatMessage(
            session_id=session_id,
            role=role,
            position=next_position,
            content=content,
            text_preview=text_preview[:2000],  # hard cap, denormalised preview
            tool_call_count=tool_call_count,
            elapsed_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        session.add(msg)

        # Bump session counters.
        chat_result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        chat = chat_result.scalar_one_or_none()
        if chat is not None:
            chat.message_count = next_position
            chat.last_message_at = datetime.now(timezone.utc).isoformat()

        await session.flush()
        return msg

    @staticmethod
    async def list_messages(
        session: AsyncSession,
        *,
        session_id: str,
        limit: Optional[int] = None,
        oldest_first: bool = True,
    ) -> list[ChatMessage]:
        """List messages in a session.

        Default ordering is oldest → newest (so the agent loop can
        replay them in chronological order). Pass ``oldest_first=False``
        for a list-view that shows the most recent N messages first.

        ``limit`` slices the query at the DB layer; useful for the
        ``recall_recent_chat`` tool and for chat list previews.
        """
        order = (
            ChatMessage.position.asc() if oldest_first
            else ChatMessage.position.desc()
        )
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(order)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_messages(
        session: AsyncSession,
        session_id: str,
    ) -> int:
        """Count messages in a session. Cheap — uses the indexed FK."""
        result = await session.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id
            )
        )
        return int(result.scalar_one() or 0)
