"""Pricing ORM model — instantiation + table metadata sanity."""

from __future__ import annotations

from app.models.pricing import (
    CityPriceIndex,
    CostFactor,
    LaborRate,
    MaterialPrice,
    PricingSnapshot,
    TradeHourEstimate,
)


def test_pricing_models_register_with_metadata():
    """Every pricing model must register on Base.metadata."""
    from app.database import Base

    expected_tables = {
        "material_prices",
        "labor_rates",
        "trade_hour_estimates",
        "city_price_indices",
        "cost_factors",
        "pricing_snapshots",
    }
    actual = {t.name for t in Base.metadata.tables.values()}
    missing = expected_tables - actual
    assert not missing, f"Tables not registered on Base.metadata: {missing}"


def test_material_price_has_convention_columns():
    cols = {c.name for c in MaterialPrice.__table__.columns}
    # Convention columns from Stage 0 mixins.
    for col in (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "version",
        "is_current",
        "previous_version_id",
        "effective_from",
        "effective_to",
        "source",
        "source_ref",
        "created_by",
    ):
        assert col in cols, f"MaterialPrice missing convention column {col!r}"
    # Business columns.
    for col in (
        "slug",
        "region",
        "name",
        "category",
        "basis_unit",
        "price_inr_low",
        "price_inr_high",
    ):
        assert col in cols


def test_labor_rate_has_band_columns():
    cols = {c.name for c in LaborRate.__table__.columns}
    assert {"trade", "region", "rate_inr_per_hour_low", "rate_inr_per_hour_high"}.issubset(cols)


def test_trade_hour_estimate_has_band_columns():
    cols = {c.name for c in TradeHourEstimate.__table__.columns}
    assert {"trade", "complexity", "hours_low", "hours_high"}.issubset(cols)


def test_city_price_index_has_multiplier():
    cols = {c.name for c in CityPriceIndex.__table__.columns}
    assert {"city_slug", "display_name", "index_multiplier", "aliases"}.issubset(cols)


def test_cost_factor_has_band_columns():
    cols = {c.name for c in CostFactor.__table__.columns}
    assert {"factor_key", "value_low", "value_high", "unit"}.issubset(cols)


def test_pricing_snapshot_is_not_versioned():
    """PricingSnapshot must NOT have versioning / soft-delete columns."""
    cols = {c.name for c in PricingSnapshot.__table__.columns}
    for forbidden in ("version", "is_current", "deleted_at", "previous_version_id"):
        assert forbidden not in cols, (
            f"PricingSnapshot must not have {forbidden!r} — it's append-only"
        )
    for required in ("snapshot_data", "source_versions", "target_type", "actor_kind"):
        assert required in cols
