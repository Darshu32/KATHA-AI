"""Stage 1 — pricing tables (schema only, no seed).

Adds the externalised cost-engine substrate:

- ``material_prices``        — material × region price band
- ``labor_rates``            — trade × region hourly rate band
- ``trade_hour_estimates``   — trade × complexity → hours band
- ``city_price_indices``     — city → multiplier + lead-time adders
- ``cost_factors``           — generic key/value bands (waste, finish, …)
- ``pricing_snapshots``      — immutable per-run snapshot rows

Each business-data table carries the Stage-0 convention columns:
``deleted_at, version, is_current, previous_version_id, effective_from,
effective_to, source, source_ref, created_by`` — and a partial unique
index ``(logical_key) WHERE is_current = TRUE AND deleted_at IS NULL``
that enforces "exactly one current version per logical key" at the DB.

Seed data is loaded by 0003_stage1_pricing_seed.py.

Revision ID: 0002_stage1_pricing
Revises: 0001_baseline
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_stage1_pricing"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _convention_columns() -> list[sa.Column]:
    """Stage-0 mixin columns shared by every versioned business-data table."""
    return [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("previous_version_id", sa.String(32), nullable=True),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.String(64),
            nullable=False,
            server_default="seed",
        ),
        sa.Column("source_ref", sa.String(512), nullable=True),
        sa.Column(
            "created_by",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ]


def _common_indexes(table: str) -> list[tuple[str, list[str]]]:
    """Indexes every versioned table benefits from."""
    return [
        (f"ix_{table}_is_current", ["is_current"]),
        (f"ix_{table}_deleted_at", ["deleted_at"]),
        (f"ix_{table}_effective_from", ["effective_from"]),
        (f"ix_{table}_effective_to", ["effective_to"]),
        (f"ix_{table}_source", ["source"]),
        (f"ix_{table}_created_by", ["created_by"]),
    ]


# ─────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # ── material_prices ──────────────────────────────────────────────
    op.create_table(
        "material_prices",
        *_convention_columns(),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column(
            "region",
            sa.String(64),
            nullable=False,
            server_default="global",
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("basis_unit", sa.String(16), nullable=False),
        sa.Column("price_inr_low", sa.Float(), nullable=False),
        sa.Column("price_inr_high", sa.Float(), nullable=False),
        sa.Column("lead_time_weeks_low", sa.Float(), nullable=True),
        sa.Column("lead_time_weeks_high", sa.Float(), nullable=True),
        sa.Column(
            "available_in_cities",
            postgresql.ARRAY(sa.String(64)),
            nullable=True,
        ),
        sa.Column(
            "extras",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.CheckConstraint(
            "price_inr_low >= 0 AND price_inr_high >= price_inr_low",
            name="ck_material_prices_price_band",
        ),
    )
    op.create_index(
        "uq_material_prices_logical_current",
        "material_prices",
        ["slug", "region"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index("ix_material_prices_slug", "material_prices", ["slug"])
    op.create_index("ix_material_prices_category", "material_prices", ["category"])
    op.create_index("ix_material_prices_region", "material_prices", ["region"])
    for name, cols in _common_indexes("material_prices"):
        op.create_index(name, "material_prices", cols)

    # ── labor_rates ──────────────────────────────────────────────────
    op.create_table(
        "labor_rates",
        *_convention_columns(),
        sa.Column("trade", sa.String(64), nullable=False),
        sa.Column(
            "region",
            sa.String(64),
            nullable=False,
            server_default="india",
        ),
        sa.Column("rate_inr_per_hour_low", sa.Float(), nullable=False),
        sa.Column("rate_inr_per_hour_high", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "rate_inr_per_hour_low >= 0 AND rate_inr_per_hour_high >= rate_inr_per_hour_low",
            name="ck_labor_rates_rate_band",
        ),
    )
    op.create_index(
        "uq_labor_rates_logical_current",
        "labor_rates",
        ["trade", "region"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index("ix_labor_rates_trade", "labor_rates", ["trade"])
    op.create_index("ix_labor_rates_region", "labor_rates", ["region"])
    for name, cols in _common_indexes("labor_rates"):
        op.create_index(name, "labor_rates", cols)

    # ── trade_hour_estimates ─────────────────────────────────────────
    op.create_table(
        "trade_hour_estimates",
        *_convention_columns(),
        sa.Column("trade", sa.String(64), nullable=False),
        sa.Column("complexity", sa.String(32), nullable=False),
        sa.Column("hours_low", sa.Float(), nullable=False),
        sa.Column("hours_high", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "hours_low >= 0 AND hours_high >= hours_low",
            name="ck_trade_hour_estimates_band",
        ),
    )
    op.create_index(
        "uq_trade_hour_estimates_logical_current",
        "trade_hour_estimates",
        ["trade", "complexity"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    for name, cols in _common_indexes("trade_hour_estimates"):
        op.create_index(name, "trade_hour_estimates", cols)

    # ── city_price_indices ───────────────────────────────────────────
    op.create_table(
        "city_price_indices",
        *_convention_columns(),
        sa.Column("city_slug", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(32), nullable=True),
        sa.Column(
            "index_multiplier",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("remote_lead_time_weeks_low", sa.Float(), nullable=True),
        sa.Column("remote_lead_time_weeks_high", sa.Float(), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.String(64)), nullable=True),
        sa.CheckConstraint(
            "index_multiplier > 0",
            name="ck_city_price_indices_positive_multiplier",
        ),
    )
    op.create_index(
        "uq_city_price_indices_logical_current",
        "city_price_indices",
        ["city_slug"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    for name, cols in _common_indexes("city_price_indices"):
        op.create_index(name, "city_price_indices", cols)

    # ── cost_factors ─────────────────────────────────────────────────
    op.create_table(
        "cost_factors",
        *_convention_columns(),
        sa.Column("factor_key", sa.String(120), nullable=False),
        sa.Column("value_low", sa.Float(), nullable=False),
        sa.Column("value_high", sa.Float(), nullable=False),
        sa.Column(
            "unit",
            sa.String(32),
            nullable=False,
            server_default="pct",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "value_high >= value_low",
            name="ck_cost_factors_band",
        ),
    )
    op.create_index(
        "uq_cost_factors_logical_current",
        "cost_factors",
        ["factor_key"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    for name, cols in _common_indexes("cost_factors"):
        op.create_index(name, "cost_factors", cols)

    # ── pricing_snapshots ────────────────────────────────────────────
    # Note: NOT versioned. Append-only.
    op.create_table(
        "pricing_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("project_id", sa.String(32), nullable=True),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("market_segment", sa.String(32), nullable=True),
        sa.Column(
            "snapshot_data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "source_versions",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "actor_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_kind",
            sa.String(64),
            nullable=False,
            server_default="system",
        ),
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_pricing_snapshots_target",
        "pricing_snapshots",
        ["target_type", "target_id"],
    )
    op.create_index(
        "ix_pricing_snapshots_project",
        "pricing_snapshots",
        ["project_id"],
    )
    op.create_index(
        "ix_pricing_snapshots_request_id",
        "pricing_snapshots",
        ["request_id"],
    )


def downgrade() -> None:
    # Reverse order to respect FK dependencies.
    op.drop_table("pricing_snapshots")
    op.drop_table("cost_factors")
    op.drop_table("city_price_indices")
    op.drop_table("trade_hour_estimates")
    op.drop_table("labor_rates")
    op.drop_table("material_prices")
