"""Stage 1 seed-extraction tests.

These run without a DB — they assert that ``build_seed_rows`` produces
the expected shape and at least the BRD-required rows. They guard
against silent breakage when someone edits a legacy knowledge file.
"""

from __future__ import annotations

import pytest

from app.knowledge import costing, regional_materials


@pytest.fixture(scope="module")
def seed():
    from app.services.pricing.seed import build_seed_rows
    return build_seed_rows()


def test_top_level_keys(seed):
    assert set(seed.keys()) == {
        "material_prices",
        "labor_rates",
        "trade_hour_estimates",
        "city_price_indices",
        "cost_factors",
    }


def test_brd_labor_trades_seeded(seed):
    trades = {row["trade"] for row in seed["labor_rates"]}
    assert {"woodworking", "welding_metal", "upholstery", "finishing", "assembly"}.issubset(trades)


def test_labor_rate_values_match_legacy(seed):
    for row in seed["labor_rates"]:
        legacy_low, legacy_high = costing.LABOR_RATES_INR_PER_HOUR[row["trade"]]
        assert row["rate_inr_per_hour_low"] == legacy_low
        assert row["rate_inr_per_hour_high"] == legacy_high


def test_brd_complexity_levels_seeded(seed):
    for row in seed["trade_hour_estimates"]:
        assert row["complexity"] in {"simple", "moderate", "complex", "highly_complex"}
    # Every BRD trade × complexity combination present (5 × 4 = 20)
    pairs = {(r["trade"], r["complexity"]) for r in seed["trade_hour_estimates"]}
    assert len(pairs) == 20


def test_city_index_aliases_recorded(seed):
    by_slug = {r["city_slug"]: r for r in seed["city_price_indices"]}
    # Aliases collapse to canonical slugs.
    assert "delhi" in by_slug
    assert "new_delhi" not in by_slug
    assert "new_delhi" in (by_slug["delhi"]["aliases"] or [])
    assert "bengaluru" in by_slug
    assert "bangalore" not in by_slug
    assert "bangalore" in (by_slug["bengaluru"]["aliases"] or [])


def test_city_index_multipliers_match_legacy(seed):
    for row in seed["city_price_indices"]:
        slug = row["city_slug"]
        assert row["index_multiplier"] == regional_materials.CITY_PRICE_INDEX[slug]


def test_brd_cost_factors_present(seed):
    keys = {row["factor_key"] for row in seed["cost_factors"]}
    expected = {
        "waste_factor_pct",
        "finish_cost_pct_of_material",
        "hardware_inr_per_piece",
        "workshop_overhead_pct_of_direct",
        "qc_pct_of_labor",
        "packaging_logistics_pct_of_product",
        "designer_markup_pct",
        "retail_markup_pct",
        "profit_margin_pct.luxury",
        "profit_margin_pct.mass_market",
    }
    assert expected.issubset(keys)


def test_cost_factor_values_match_legacy(seed):
    by_key = {r["factor_key"]: r for r in seed["cost_factors"]}
    waste = by_key["waste_factor_pct"]
    assert waste["value_low"] == costing.WASTE_FACTOR_PCT[0]
    assert waste["value_high"] == costing.WASTE_FACTOR_PCT[1]

    qc = by_key["qc_pct_of_labor"]
    assert qc["value_low"] == costing.QC_PCT_OF_LABOR[0]
    assert qc["value_high"] == costing.QC_PCT_OF_LABOR[1]


def test_walnut_price_seeded(seed):
    walnut = next(
        (r for r in seed["material_prices"] if r["slug"] == "walnut"), None
    )
    assert walnut is not None
    assert walnut["category"] == "wood_solid"
    assert walnut["basis_unit"] == "kg"
    # Legacy value: cost_inr_kg = (500, 800)
    assert walnut["price_inr_low"] == 500
    assert walnut["price_inr_high"] == 800


def test_band_invariants(seed):
    """Every band row has low <= high and prices >= 0."""
    for row in seed["material_prices"]:
        assert row["price_inr_low"] >= 0
        assert row["price_inr_high"] >= row["price_inr_low"]
    for row in seed["labor_rates"]:
        assert row["rate_inr_per_hour_low"] >= 0
        assert row["rate_inr_per_hour_high"] >= row["rate_inr_per_hour_low"]
    for row in seed["trade_hour_estimates"]:
        assert row["hours_low"] >= 0
        assert row["hours_high"] >= row["hours_low"]
    for row in seed["cost_factors"]:
        assert row["value_high"] >= row["value_low"]
    for row in seed["city_price_indices"]:
        assert row["index_multiplier"] > 0


def test_every_row_has_source_tag(seed):
    for table, rows in seed.items():
        for row in rows:
            assert row.get("source", "").startswith("seed:"), (
                f"{table} row missing seed source tag: {row}"
            )
