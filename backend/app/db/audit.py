"""Audit log — append-only record of every meaningful change in the system.

Every business-data write (price update, theme change, code override) and
every meaningful agent action (tool call, decision recorded) writes a row
here. This is the spine of:

- Stage 11 (transparency): "why did the agent pick teak?"
- Compliance audits: "show me every NBC override approved last quarter"
- Debugging: "what changed between this estimate and yesterday's?"

Design notes
------------
- **Append-only.** Never UPDATE or DELETE rows in this table.
- **JSON before/after** so we don't need a schema per audited entity.
- **target_type + target_id** form a soft FK; we don't enforce it because
  audit events outlive the rows they reference (soft-deleted rows still
  have audit history).
- **Indexed on (target_type, target_id, created_at desc)** for fast
  "history of X" queries.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UUIDMixin


class AuditEvent(Base, UUIDMixin):
    """One row per recorded action. See module docstring for design notes."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_target_history",
            "target_type",
            "target_id",
            "created_at",
        ),
        Index("ix_audit_events_actor_recent", "actor_id", "created_at"),
    )

    # When (immutable, server-side default for guarantee).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Who. Nullable for system actors (seeds, scrapers, scheduled jobs).
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Free-form actor descriptor when no user is involved
    # ("system:seed", "scraper:mcx", "agent:cost_engine_tool").
    actor_kind: Mapped[str] = mapped_column(
        String(64), default="user", nullable=False, index=True
    )

    # What.
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # ``create`` | ``update`` | ``soft_delete`` | ``override`` |
    # ``tool_call`` | ``decision`` | ``import`` | ``export`` | ...

    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Logical entity name: ``material_price``, ``theme``, ``project``,
    # ``estimate``, ``design_graph``, ...

    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Usually the row's UUID. For aggregate actions, may be a synthetic key.

    # Diff payload.
    before: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Human / machine context.
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ─────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────


class AuditLog:
    """Thin convenience wrapper over the AuditEvent table.

    Usage::

        async with session.begin():
            new_price = MaterialPrice(...)
            session.add(new_price)
            await session.flush()  # populate id
            await AuditLog.record(
                session,
                actor_id=user.id,
                action="create",
                target_type="material_price",
                target_id=new_price.id,
                after=new_price_to_dict(new_price),
                reason="Monthly price update sheet",
            )

    The caller controls the transaction. AuditLog.record() never commits;
    it just adds the AuditEvent to the session.
    """

    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        action: str,
        target_type: str,
        target_id: str,
        actor_id: Optional[str] = None,
        actor_kind: str = "user",
        before: Optional[dict[str, Any]] = None,
        after: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """Record one audit event. Caller manages the transaction."""
        event = AuditEvent(
            actor_id=actor_id,
            actor_kind=actor_kind if actor_id is None else "user",
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before=before or {},
            after=after or {},
            reason=reason,
            request_id=request_id,
            extra=extra or {},
        )
        session.add(event)
        return event
