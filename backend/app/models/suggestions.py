"""Stage 3F — chat-suggestion-chip ORM model.

Externalises the hardcoded ``DEFAULT_SUGGESTIONS`` array in
``frontend/components/chat/suggestion-chips.tsx`` so designers can
update the prompt suggestions surfaced to architects without a
frontend deploy.

Why a dedicated table (not a row in ``building_standards``)?
  - Suggestions are **UX content**, not compliance / building data.
  - The public ``GET /suggestions`` endpoint is anonymous — collapsing
    it into the building-standards admin path would break authn.
  - Different lifecycle: chips are A/B tested, weighted, ordered.

Logical key
-----------
``slug`` — kebab/snake-case identifier (``modern_villa_facade_ideas``).
Partial unique index ``(slug) WHERE is_current = TRUE AND deleted_at
IS NULL`` enforces "exactly one current version per slug".

Context
-------
Where the chip is shown:
  - ``chat_empty_hero``   — the welcome hero before any messages
  - ``brief_intake``      — design-brief flow (Stage 4+)
  - ``cost_followup``     — after a cost-engine answer (Stage 4+)
  - ``post_generation``   — after design generation (future)

Multiple contexts per chip is supported via the ``contexts`` array
column.

Weight
------
Higher = surfaces sooner. Default 100. Allows admin to promote/demote
chips without deleting them.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.db.conventions import (
    ActorMixin,
    EffectiveDatesMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    UUIDMixin,
    VersionedMixin,
)


class Suggestion(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """One chat-suggestion chip (label + prompt + context tagging)."""

    __tablename__ = "suggestions"
    __table_args__ = (
        Index(
            "uq_suggestions_logical_current",
            "slug",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_suggestions_status", "status"),
        Index("ix_suggestions_weight", "weight"),
    )

    # ── Logical key ───────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(String(120), nullable=False)

    # ── Display ───────────────────────────────────────────────────
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    """Short button text shown on the chip."""

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    """Full prompt text dispatched to the agent on click."""

    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    """Optional internal note for admins (not surfaced to users)."""

    # ── Routing ───────────────────────────────────────────────────
    contexts: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        default=list,
    )
    """Where the chip appears. Empty = global (any context)."""

    # ── Ordering + status ─────────────────────────────────────────
    weight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    """Higher surfaces earlier. Default 100; range typically 0–200."""

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="published"
    )
    """``draft`` | ``published`` | ``archived``."""

    # ── Tags (free-form for analytics + filtering) ────────────────
    tags: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    """e.g. ``["facade", "modern"]``, ``["sustainability"]``."""
