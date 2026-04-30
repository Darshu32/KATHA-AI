"""Stage 1 — pricing seed data.

Loads the legacy ``app.knowledge`` constants into the Stage 1 pricing
tables. Idempotent on a fresh database; a re-run is a no-op when rows
with the same logical key already exist (the partial unique index in
0002 stops duplicates).

The actual row generation lives in
``app.services.pricing.seed.build_seed_rows`` so unit tests can assert
against the same dictionary the migration inserts.

Revision ID: 0003_stage1_pricing_seed
Revises: 0002_stage1_pricing
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.pricing.seed import build_seed_rows

# revision identifiers, used by Alembic.
revision = "0003_stage1_pricing_seed"
down_revision = "0002_stage1_pricing"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────
# Lightweight ``Table`` references — only the columns we INSERT into.
# Migrations should not import the ORM (would couple migration state to
# current model code), so we describe the bare-minimum table here.
# ─────────────────────────────────────────────────────────────────────


def _material_prices_table() -> sa.Table:
    return sa.table(
        "material_prices",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("region", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("basis_unit", sa.String),
        sa.column("price_inr_low", sa.Float),
        sa.column("price_inr_high", sa.Float),
        sa.column("lead_time_weeks_low", sa.Float),
        sa.column("lead_time_weeks_high", sa.Float),
        sa.column("available_in_cities", postgresql.ARRAY(sa.String)),
        sa.column("extras", postgresql.JSONB),
        sa.column("source", sa.String),
    )


def _labor_rates_table() -> sa.Table:
    return sa.table(
        "labor_rates",
        sa.column("id", sa.String),
        sa.column("trade", sa.String),
        sa.column("region", sa.String),
        sa.column("rate_inr_per_hour_low", sa.Float),
        sa.column("rate_inr_per_hour_high", sa.Float),
        sa.column("notes", sa.Text),
        sa.column("source", sa.String),
    )


def _trade_hour_estimates_table() -> sa.Table:
    return sa.table(
        "trade_hour_estimates",
        sa.column("id", sa.String),
        sa.column("trade", sa.String),
        sa.column("complexity", sa.String),
        sa.column("hours_low", sa.Float),
        sa.column("hours_high", sa.Float),
        sa.column("notes", sa.Text),
        sa.column("source", sa.String),
    )


def _city_price_indices_table() -> sa.Table:
    return sa.table(
        "city_price_indices",
        sa.column("id", sa.String),
        sa.column("city_slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("state", sa.String),
        sa.column("tier", sa.String),
        sa.column("index_multiplier", sa.Float),
        sa.column("remote_lead_time_weeks_low", sa.Float),
        sa.column("remote_lead_time_weeks_high", sa.Float),
        sa.column("aliases", postgresql.ARRAY(sa.String)),
        sa.column("source", sa.String),
    )


def _cost_factors_table() -> sa.Table:
    return sa.table(
        "cost_factors",
        sa.column("id", sa.String),
        sa.column("factor_key", sa.String),
        sa.column("value_low", sa.Float),
        sa.column("value_high", sa.Float),
        sa.column("unit", sa.String),
        sa.column("description", sa.Text),
        sa.column("source", sa.String),
    )


# ─────────────────────────────────────────────────────────────────────
# Upgrade / downgrade
# ─────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    rows = build_seed_rows()

    # All convention columns (version, is_current, effective_from, …)
    # rely on server-side defaults defined in 0002, so we only insert
    # business columns + id + source.
    op.bulk_insert(_material_prices_table(), rows["material_prices"])
    op.bulk_insert(_labor_rates_table(), rows["labor_rates"])
    op.bulk_insert(_trade_hour_estimates_table(), rows["trade_hour_estimates"])
    op.bulk_insert(_city_price_indices_table(), rows["city_price_indices"])
    op.bulk_insert(_cost_factors_table(), rows["cost_factors"])


def downgrade() -> None:
    # Wipe seed rows — leave any admin-created rows alone by filtering
    # on source LIKE 'seed:%'.
    bind = op.get_bind()
    for table in (
        "material_prices",
        "labor_rates",
        "trade_hour_estimates",
        "city_price_indices",
        "cost_factors",
    ):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE source LIKE 'seed:%'"))
