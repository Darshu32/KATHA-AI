"""SQLAlchemy mixins that encode KATHA-AI's data conventions.

Every business-data model (prices, themes, standards, materials, …) should
compose from these mixins. They make versioning, soft-delete, time-bounded
validity, source tracking, and audit columns *uniform across the system*.

Why this matters
----------------
- Solo dev means future-you needs the same shape on every table — no
  surprises when querying or migrating.
- Stage 1 (pricing externalization) snapshots prices into estimates by
  effective date. That guarantee depends on these columns existing.
- Stage 11 (transparency) traces every recommendation back to a source row;
  ``SourceMixin`` is what makes that traceability possible.

Re-exports the legacy ``UUIDMixin``/``TimestampMixin`` from
``app.database`` so that callers only need to import from ``app.db``.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

# Re-export the foundational mixins from app.database so this module can be
# the single import surface for "data layer primitives".
from app.database import TimestampMixin, UUIDMixin  # noqa: F401  (re-export)


# ─────────────────────────────────────────────────────────────────────────
# Soft delete
# ─────────────────────────────────────────────────────────────────────────


class SoftDeleteMixin:
    """Records are *soft* deleted — never physically removed.

    Repositories filter out rows where ``deleted_at IS NOT NULL`` by default.
    Use this for any business data that another row might reference (prices,
    themes, materials, …). Audit trails depend on the row continuing to exist.
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# ─────────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────────


class VersionedMixin:
    """Append-only versioning for business data.

    Pattern
    -------
    Every "logical" record (e.g. *the price of walnut in Mumbai*) is
    represented by **multiple rows**, one per version. Updates *create new
    rows* rather than mutating existing ones. This guarantees:

    - Old estimates reproduce with their original prices forever
    - We can answer "what was the price on date X?"
    - Rollback is a row insert, not a destructive operation

    Columns
    -------
    - ``version``           : monotonically increasing per logical key
    - ``previous_version_id`` : link back to the row this one supersedes
    - ``is_current``        : exactly one row per logical key has this true

    Subclasses must define their own *logical-key* columns and a partial
    unique index ``(logical_key, is_current) WHERE is_current = TRUE`` in
    a migration to enforce single-current-version invariant at the DB level.
    """

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        default=True, nullable=False, index=True
    )
    previous_version_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )


# ─────────────────────────────────────────────────────────────────────────
# Effective dates (time-bounded validity)
# ─────────────────────────────────────────────────────────────────────────


class EffectiveDatesMixin:
    """Time-bounded validity for prices, codes, theme rules, and standards.

    A row is "active" at time *T* iff ``effective_from <= T < effective_to``
    (with ``effective_to = NULL`` meaning open-ended).

    Combined with ``VersionedMixin`` this gives us: at any point in time,
    exactly one version is canonical. Stage 1 uses this to snapshot prices
    onto estimates: ``get_price(material, city, as_of=estimate_created_at)``.
    """

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    effective_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    def is_active_at(self, when: datetime) -> bool:
        """True if this row was/is canonical at the given instant."""
        if when < self.effective_from:
            return False
        if self.effective_to is not None and when >= self.effective_to:
            return False
        return True


# ─────────────────────────────────────────────────────────────────────────
# Source tracking
# ─────────────────────────────────────────────────────────────────────────


class SourceMixin:
    """Where did this row come from?

    Stage 11 (transparency) needs every datum to be traceable. We tag each
    row with:

    - ``source``     : free-form short tag — ``"seed"``, ``"admin"``,
                        ``"mcx_scraper"``, ``"vendor:jaquar"``, ``"rag:nbc-2016"``
    - ``source_ref`` : optional URL, document section, vendor SKU, etc.
    - ``source_meta``: JSON for richer provenance (page numbers, request IDs)

    Conventions
    -----------
    Use ``"seed"`` for migration-time inserts, ``"admin"`` for human edits,
    ``"<integration>"`` for automated feeds. Never leave ``source`` blank —
    it's how we audit data quality later.
    """

    source: Mapped[str] = mapped_column(
        String(64), default="seed", nullable=False, index=True
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )


# ─────────────────────────────────────────────────────────────────────────
# Actor tracking
# ─────────────────────────────────────────────────────────────────────────


class ActorMixin:
    """Who created / last touched this row?

    For business data, ``created_by`` is the user (or system actor) that
    wrote the row. For ``VersionedMixin`` rows specifically, this answers
    "who promoted this version?".

    Nullable because seed data and automated feeds may not have a user.
    """

    created_by: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
