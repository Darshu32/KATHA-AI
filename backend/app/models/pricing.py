"""Stage 1 — pricing ORM models.

Externalises the cost-engine constants that previously lived as Python
literals in ``app.knowledge.costing``, ``app.knowledge.regional_materials``
and (the cost-related parts of) ``app.knowledge.materials``.

Design notes
------------
- Every business-data model composes the full Stage-0 mixin set:
  ``UUIDMixin + TimestampMixin + SoftDeleteMixin + VersionedMixin
  + EffectiveDatesMixin + SourceMixin + ActorMixin``.

- "Logical key" is the natural identifier of the *thing* the row
  describes (``material_prices.slug + region``, ``labor_rates.trade +
  region``, ``city_price_indices.city_slug``, etc). The migration
  enforces "exactly one current version per logical key" via a partial
  unique index ``WHERE is_current = TRUE AND deleted_at IS NULL``.

- Bands (e.g. ``₹300-800/kg``) are stored as two columns ``*_low`` /
  ``*_high`` rather than a single JSONB blob — querying inside Postgres
  stays trivial and snapshots remain readable.

- ``PricingSnapshot`` is the immutable record of what prices were
  active when an estimate / cost-engine run was produced. Re-fetching
  an old estimate replays its snapshot, so the numbers never drift.

This module is imported by the Alembic baseline migration target
metadata (see ``backend/alembic/env.py``).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, String, Text, text
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


# ─────────────────────────────────────────────────────────────────────
# Material prices
# ─────────────────────────────────────────────────────────────────────


class MaterialPrice(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """Per-material price band, optionally scoped to a region.

    Logical key is ``(slug, region)``. ``region="global"`` is the
    catch-all baseline; specific city/region rows override it when
    the cost engine asks for a price scoped to that location.

    The price is stored as a band ``[price_inr_low, price_inr_high]``
    against the unit declared by ``basis_unit`` (e.g. ``kg``, ``m2``,
    ``m3``, ``linear_m``, ``piece``). Cost-engine line items use the
    midpoint by default, the LLM cites either bound when relevant.
    """

    __tablename__ = "material_prices"
    __table_args__ = (
        Index(
            "uq_material_prices_logical_current",
            "slug",
            "region",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_material_prices_slug", "slug"),
        Index("ix_material_prices_category", "category"),
        Index("ix_material_prices_region", "region"),
    )

    # Logical key.
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(
        String(64), nullable=False, default="global"
    )

    # Display + categorisation.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    # ``wood_solid`` | ``wood_panel`` | ``metal`` | ``stone`` | ``glass``
    # | ``leather`` | ``fabric`` | ``foam`` | ``tile`` | ``finish`` | ``hardware``.

    # Pricing band.
    basis_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    # ``kg`` | ``m2`` | ``m3`` | ``linear_m`` | ``piece``.
    price_inr_low: Mapped[float] = mapped_column(Float, nullable=False)
    price_inr_high: Mapped[float] = mapped_column(Float, nullable=False)

    # Procurement context.
    lead_time_weeks_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lead_time_weeks_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    available_in_cities: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    # If ``["*"]`` material is universally available; if NULL availability
    # is unknown / not tracked.

    # Free-form structured extras (finish options, aesthetic notes, …).
    extras: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# ─────────────────────────────────────────────────────────────────────
# Labor rates
# ─────────────────────────────────────────────────────────────────────


class LaborRate(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """Per-trade hourly rate band.

    Logical key ``(trade, region)``. ``region="india"`` is the BRD
    baseline; city-specific overrides scale via ``CityPriceIndex``
    rather than per-row data.

    BRD §1C trades:
      ``woodworking`` (₹200-400/hr), ``welding_metal`` (₹150-300),
      ``upholstery`` (₹100-200), ``finishing`` (₹100-150),
      ``assembly`` (₹50-100).
    """

    __tablename__ = "labor_rates"
    __table_args__ = (
        Index(
            "uq_labor_rates_logical_current",
            "trade",
            "region",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index("ix_labor_rates_trade", "trade"),
        Index("ix_labor_rates_region", "region"),
    )

    trade: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(
        String(64), nullable=False, default="india"
    )
    rate_inr_per_hour_low: Mapped[float] = mapped_column(Float, nullable=False)
    rate_inr_per_hour_high: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─────────────────────────────────────────────────────────────────────
# Trade hours by complexity
# ─────────────────────────────────────────────────────────────────────


class TradeHourEstimate(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """Hours-per-piece for a trade at a given complexity level.

    Logical key ``(trade, complexity)``. Drives the cost engine's
    "labor hours band" prompt slot — combined with ``LaborRate`` to
    produce a labor cost band.

    Complexity levels: ``simple`` | ``moderate`` | ``complex``
    | ``highly_complex``.
    """

    __tablename__ = "trade_hour_estimates"
    __table_args__ = (
        Index(
            "uq_trade_hour_estimates_logical_current",
            "trade",
            "complexity",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
    )

    trade: Mapped[str] = mapped_column(String(64), nullable=False)
    complexity: Mapped[str] = mapped_column(String(32), nullable=False)
    hours_low: Mapped[float] = mapped_column(Float, nullable=False)
    hours_high: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─────────────────────────────────────────────────────────────────────
# City price index
# ─────────────────────────────────────────────────────────────────────


class CityPriceIndex(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """Per-city cost multiplier and lead-time adder.

    Logical key: ``city_slug``. ``index_multiplier`` scales material
    + labor rates; lead-time adders represent the extra weeks for
    materials that aren't locally produced.

    Tier values (free-form): ``tier1`` | ``tier2`` | ``tier3``
    | ``remote`` | ``hill``. Used for analytics and bulk pricing
    rules; the multiplier is the canonical adjustment.
    """

    __tablename__ = "city_price_indices"
    __table_args__ = (
        Index(
            "uq_city_price_indices_logical_current",
            "city_slug",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
    )

    city_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    index_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    remote_lead_time_weeks_low: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    remote_lead_time_weeks_high: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    aliases: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(String(64)), nullable=True
    )
    # e.g. ``new_delhi`` aliases to ``delhi``; ``bangalore`` ↔ ``bengaluru``.


# ─────────────────────────────────────────────────────────────────────
# Cost factors (waste %, finish %, hardware band, overhead %, etc.)
# ─────────────────────────────────────────────────────────────────────


class CostFactor(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """Generic key/value band for cost-engine constants.

    Logical key: ``factor_key``. The value is always stored as a band
    ``[value_low, value_high]``. The unit is free text (``pct`` |
    ``inr_per_piece`` | …) so this single table accommodates every
    BRD §4A constant.

    Known keys (seed):
      - ``waste_factor_pct``                 → (10, 15)
      - ``finish_cost_pct_of_material``      → (15, 25)
      - ``hardware_inr_per_piece``           → (500, 2000)
      - ``workshop_overhead_pct_of_direct``  → (30, 40)
      - ``qc_pct_of_labor``                  → (5, 10)
      - ``packaging_logistics_pct_of_product`` → (10, 15)
      - ``profit_margin_pct.luxury``         → (40, 60)
      - ``profit_margin_pct.mass_market``    → (30, 40)
      - ``designer_markup_pct``              → (25, 50)
      - ``customization_premium_pct``        → (10, 25)
    """

    __tablename__ = "cost_factors"
    __table_args__ = (
        Index(
            "uq_cost_factors_logical_current",
            "factor_key",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
    )

    factor_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value_low: Mapped[float] = mapped_column(Float, nullable=False)
    value_high: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="pct")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─────────────────────────────────────────────────────────────────────
# Pricing snapshots (immutable)
# ─────────────────────────────────────────────────────────────────────


class PricingSnapshot(Base, UUIDMixin, TimestampMixin):
    """Immutable record of every pricing constant that was active at
    the moment a cost-engine run / estimate was produced.

    Why: when an admin updates a material price tomorrow, today's BOQ
    must continue to compute the same numbers it computed today. The
    snapshot stores the *full* dict the LLM saw, so the same run can be
    replayed forever.

    Notes
    -----
    - This table is **not versioned** — every row is created fresh and
      never mutated. No ``VersionedMixin``, no ``SoftDeleteMixin``.
    - ``snapshot_data`` is the entire ``cost_brd`` + city + materials
      dict the LLM was prompted with. Schema is intentionally schemaless
      (JSONB) so we can extend the cost-engine prompt without migration.
    - ``target_type``/``target_id`` form a soft FK to the artefact
      that owns the snapshot (estimate, cost_engine response, …).
    """

    __tablename__ = "pricing_snapshots"
    __table_args__ = (
        Index(
            "ix_pricing_snapshots_target",
            "target_type",
            "target_id",
        ),
    )

    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # ``cost_engine`` | ``estimate_snapshot`` | ``manual``.
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Free-form labels for analytics and audit.
    project_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    market_segment: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # The captured dict. See ``app.services.pricing.snapshot_service`` for shape.
    snapshot_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Versions of the source rows used. Lets us answer "which material
    # price version was this snapshot built from?" without scanning the blob.
    source_versions: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Who triggered the capture (user / agent tool / system). Nullable
    # because seed data and migrations capture snapshots without an actor.
    actor_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    actor_kind: Mapped[str] = mapped_column(
        String(64), nullable=False, default="system"
    )
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
