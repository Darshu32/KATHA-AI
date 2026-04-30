"""Stage 3A — themes ORM model.

Externalises ``app.knowledge.themes`` so senior designers can edit and
clone themes without code changes. Rule packs are stored as JSONB so
the schema doesn't need to evolve every time a designer adds a new
field (signature_moves, dos/donts, ergonomic_targets, etc.).

Logical key
-----------
``slug`` — kebab-or-snake case identifier (``modern``,
``mid_century_modern``, ``pedestal``). Partial unique index in the
migration enforces "one current version per slug".

Status workflow
---------------
``draft`` → ``published`` → optionally ``archived`` (soft delete).

Only ``published`` rows are visible to the cost engine and agent
tools. Designers iterate in ``draft`` until they're happy, then
publish.

Cloning
-------
Designers create variants ("Modern → Modern Luxe") by cloning an
existing theme. The clone gets a fresh ``slug`` and a new
``version=1`` (it's a new logical record, not a new version of an
existing one). The original is unaffected.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class Theme(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """One theme rule pack — all the parametric rules for a design style."""

    __tablename__ = "themes"
    __table_args__ = (
        Index(
            "uq_themes_logical_current",
            "slug",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_themes_slug", "slug"),
        Index("ix_themes_status", "status"),
    )

    # ── Logical key ───────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── Display ───────────────────────────────────────────────────
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    era: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # ── Status ────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="published"
    )
    # ``draft`` | ``published`` | ``archived``.

    # ── Rule pack (the substance) ────────────────────────────────
    # The full design vocabulary the LLM consumes. Schemaless to
    # keep iteration cheap; see :mod:`app.services.themes_service`
    # for the canonical key list.
    rule_pack: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Aliases ───────────────────────────────────────────────────
    # Loose / legacy strings the resolver maps to this theme:
    # ``["midcentury", "mid-century", "mcm"]`` → ``mid_century_modern``.
    aliases: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(64)), nullable=True
    )

    # ── Lineage ───────────────────────────────────────────────────
    # When a designer clones an existing theme, ``cloned_from_slug``
    # records the parent so the analytics + audit trail stay coherent.
    # NOT a foreign key — preserves history if the parent is renamed.
    cloned_from_slug: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    # ── Preview imagery ──────────────────────────────────────────
    # Storage keys (R2/S3) for theme reference imagery. Stage 7
    # (multimodal) populates these from designer uploads.
    preview_image_keys: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(512)), nullable=True
    )
