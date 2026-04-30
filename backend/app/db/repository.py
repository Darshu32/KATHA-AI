"""Generic repository base — the data-access pattern for KATHA-AI.

Why a repository pattern?
-------------------------
Solo dev means scattered ``session.execute(select(X)...)`` calls turn into
a maintenance nightmare. Repositories give us:

1. **One place** for filters that *every* query must apply (soft-delete,
   ``is_current=True``, effective-date windows).
2. **Cache-friendly** reads — Stage 0 ships ``BaseRepository.get()`` with a
   Redis decorator hook so Stage 1 can flip caching on without rewriting.
3. **Audit-friendly** writes — ``create_versioned`` and ``soft_delete``
   emit ``AuditEvent`` rows automatically.

How to use
----------
Subclass ``BaseRepository`` per ORM model::

    class MaterialRepository(BaseRepository[Material]):
        model = Material

        async def get_active_for(
            self, *, name: str, region: str, when: datetime,
        ) -> Material | None:
            stmt = self._active_at(when).where(
                Material.name == name, Material.region == region,
            )
            return (await self.session.execute(stmt)).scalar_one_or_none()

Stage 1 will be the first real consumer; Stages 3–10 will follow the same
recipe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Optional, Type, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import AuditLog
from app.db.conventions import (
    EffectiveDatesMixin,
    SoftDeleteMixin,
    VersionedMixin,
)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base class for all data repositories.

    Subclass and set ``model`` to your ORM class. Inherit only the helpers
    you need — the methods are defensive about whether the model uses
    ``SoftDeleteMixin``, ``VersionedMixin``, or ``EffectiveDatesMixin``.
    """

    model: Type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Query primitives ──────────────────────────────────────────────

    def _base_select(self) -> Select[Any]:
        """Select that respects soft-delete (if applicable)."""
        stmt = select(self.model)
        if issubclass(self.model, SoftDeleteMixin):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    def _current_select(self) -> Select[Any]:
        """Select that returns only the current version of versioned rows."""
        stmt = self._base_select()
        if issubclass(self.model, VersionedMixin):
            stmt = stmt.where(self.model.is_current.is_(True))  # type: ignore[attr-defined]
        return stmt

    def _active_at(self, when: datetime) -> Select[Any]:
        """Select rows that are active at the given instant.

        Active = not soft-deleted, current version (if versioned),
        and inside the effective-date window (if dated).
        """
        stmt = self._current_select()
        if issubclass(self.model, EffectiveDatesMixin):
            stmt = stmt.where(self.model.effective_from <= when)  # type: ignore[attr-defined]
            stmt = stmt.where(
                (self.model.effective_to.is_(None))  # type: ignore[attr-defined]
                | (self.model.effective_to > when)  # type: ignore[attr-defined]
            )
        return stmt

    # ── Reads ─────────────────────────────────────────────────────────

    async def get(self, id_: str) -> Optional[T]:
        """Fetch one row by primary key. Honors soft-delete."""
        stmt = self._base_select().where(self.model.id == id_)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, limit: int = 100, offset: int = 0) -> list[T]:
        """List active rows. Honors soft-delete + current-version."""
        stmt = self._current_select().limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Writes ────────────────────────────────────────────────────────

    async def create(
        self,
        data: dict[str, Any],
        *,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> T:
        """Insert a new row and write an audit event.

        For versioned rows, the inserted row is the *first* version
        (``version=1, is_current=True``). To create a *new version* of an
        existing logical record, use ``create_versioned``.
        """
        instance = self.model(**data)  # type: ignore[call-arg]
        self.session.add(instance)
        await self.session.flush()  # populate id

        await AuditLog.record(
            self.session,
            action="create",
            target_type=self.model.__tablename__,  # type: ignore[attr-defined]
            target_id=instance.id,  # type: ignore[attr-defined]
            actor_id=actor_id,
            after=_to_audit_dict(instance),
            reason=reason,
            request_id=request_id,
        )
        return instance

    async def create_versioned(
        self,
        previous: T,
        changes: dict[str, Any],
        *,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> T:
        """Append a new version that supersedes ``previous``.

        - Marks the previous row's ``is_current=False``
        - Closes its ``effective_to`` to "now" (if dated)
        - Inserts a new row with version+1, ``is_current=True``,
          ``previous_version_id=previous.id``, ``effective_from=now``
        - Writes an audit event with full before/after diff

        ``changes`` should contain only the columns being updated; all
        other columns are inherited from ``previous``.
        """
        if not isinstance(previous, VersionedMixin):
            raise TypeError(
                f"{type(previous).__name__} does not support versioning"
            )

        now = datetime.now(timezone.utc)

        # Capture before state for audit BEFORE we mutate anything.
        before = _to_audit_dict(previous)

        # Demote the previous row.
        previous.is_current = False  # type: ignore[attr-defined]
        if isinstance(previous, EffectiveDatesMixin):
            if previous.effective_to is None:  # type: ignore[attr-defined]
                previous.effective_to = now  # type: ignore[attr-defined]

        # Build the new version, inheriting columns from ``previous``.
        inherited = _to_audit_dict(previous)
        inherited.pop("id", None)
        inherited.pop("version", None)
        inherited.pop("previous_version_id", None)
        inherited.pop("is_current", None)
        inherited.pop("effective_from", None)
        inherited.pop("effective_to", None)
        inherited.pop("created_at", None)
        inherited.pop("updated_at", None)

        merged = {**inherited, **changes}
        merged["version"] = previous.version + 1  # type: ignore[attr-defined]
        merged["previous_version_id"] = previous.id  # type: ignore[attr-defined]
        merged["is_current"] = True
        if issubclass(self.model, EffectiveDatesMixin):
            merged.setdefault("effective_from", now)
            merged["effective_to"] = None

        new_instance = self.model(**merged)  # type: ignore[call-arg]
        self.session.add(new_instance)
        await self.session.flush()

        await AuditLog.record(
            self.session,
            action="update",
            target_type=self.model.__tablename__,  # type: ignore[attr-defined]
            target_id=new_instance.id,  # type: ignore[attr-defined]
            actor_id=actor_id,
            before=before,
            after=_to_audit_dict(new_instance),
            reason=reason,
            request_id=request_id,
            extra={"previous_version_id": previous.id},  # type: ignore[attr-defined]
        )
        return new_instance

    async def soft_delete(
        self,
        instance: T,
        *,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> T:
        """Soft-delete a row. Audit event recorded."""
        if not isinstance(instance, SoftDeleteMixin):
            raise TypeError(
                f"{type(instance).__name__} does not support soft-delete"
            )

        before = _to_audit_dict(instance)
        instance.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        await AuditLog.record(
            self.session,
            action="soft_delete",
            target_type=self.model.__tablename__,  # type: ignore[attr-defined]
            target_id=instance.id,  # type: ignore[attr-defined]
            actor_id=actor_id,
            before=before,
            after=_to_audit_dict(instance),
            reason=reason,
            request_id=request_id,
        )
        return instance


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _to_audit_dict(instance: Any) -> dict[str, Any]:
    """Serialize an ORM instance into a JSON-safe dict for audit storage.

    Skips relationships and private attributes. Datetimes are ISO strings.
    """
    out: dict[str, Any] = {}
    for column in instance.__table__.columns:
        value = getattr(instance, column.name, None)
        if isinstance(value, datetime):
            value = value.isoformat()
        out[column.name] = value
    return out
