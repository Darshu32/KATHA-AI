"""Stage 3B — building standards ORM model.

Externalises ``app.knowledge.clearances`` and
``app.knowledge.space_standards``. Both are conceptually building
rules with jurisdictional variants, so we collapse them into a single
``standards`` table keyed on ``(slug, category, jurisdiction)``.

Categories
----------
Stage 3B ships ``clearance`` and ``space``. Stage 3C will add ``mep``;
Stage 3E will add ``code``. The same row shape works for all of them
because the variable-shape data lives in the JSONB ``data`` column.

Jurisdiction
------------
``india_nbc`` is the BRD baseline. ``international_ibc`` is the global
fallback. Specific cities / states (e.g. ``maharashtra_dcr``,
``karnataka_kmc``) override the baseline when a project is scoped
to that jurisdiction. The repository's resolver picks the most
specific row available and falls back to the baseline.

Citation
--------
``source_section`` is filled in from BRD / NBC / IBC at seed time
(e.g. ``"NBC 2016 Part 4 §3.2"``) so Stage 11 transparency can
attribute every recommendation to its source clause.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
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


class BuildingStandard(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """One row per building rule (clearance, space requirement, MEP target …).

    Logical key: ``(slug, category, jurisdiction)``. Migration enforces
    the partial-unique invariant.
    """

    __tablename__ = "building_standards"
    __table_args__ = (
        Index(
            "uq_building_standards_logical_current",
            "slug",
            "category",
            "jurisdiction",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_building_standards_category_juris", "category", "jurisdiction"),
        Index("ix_building_standards_subcategory", "subcategory"),
        Index("ix_building_standards_slug", "slug"),
    )

    # ── Logical key ───────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # ``clearance`` | ``space`` | ``mep`` (Stage 3C) | ``manufacturing``
    # (Stage 3D) | ``code`` (Stage 3E).

    jurisdiction: Mapped[str] = mapped_column(
        String(64), nullable=False, default="india_nbc"
    )

    # ── Categorisation ────────────────────────────────────────────
    subcategory: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # clearance:     ``door`` | ``window`` | ``corridor`` | ``stair`` | ``ramp``
    #                | ``circulation`` | ``egress``
    # space:         ``residential_room`` | ``commercial_room`` | ``hospitality_room``
    # mep:           ``hvac`` | ``electrical`` | ``plumbing`` | ``system_cost``
    # manufacturing: ``tolerance`` | ``joinery`` | ``welding`` | ``lead_time``
    #                | ``moq`` | ``qa_gate`` | ``process_spec``
    # code:          ``fire`` | ``accessibility`` | ``energy`` | ``structural``

    # ── Display ───────────────────────────────────────────────────
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Data (the actual rule) ───────────────────────────────────
    # Free-form JSONB. Examples:
    #   door:          {"width_mm": [1000, 1200], "height_mm": [2100, 2400]}
    #   bedroom:       {"min_area_m2": 9, "typical_area_m2": 12,
    #                   "min_short_side_m": 2.7, "min_height_m": 2.7}
    #   circulation:   {"clearance_mm": 600}
    #   egress (rule): {"max_travel_distance_m": 30,
    #                   "min_exit_count_over_50_occupants": 2}
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Citation ──────────────────────────────────────────────────
    source_section: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # e.g. ``"NBC 2016 Part 4 §3.2.1"``, ``"IBC Chapter 10 §1010"``,
    # ``"BRD Layer 1B — clearance & egress"``.
    source_doc: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # e.g. ``"NBC-2016"``, ``"IBC-2021"``, ``"BRD-Phase-1"``.
