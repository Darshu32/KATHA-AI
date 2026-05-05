"""Stage 12 — live data feeds tables.

Three new tables underpin the self-refreshing pricing engine:

- ``live_price_quotes``     — versioned per ``(feed_source, commodity_key)``.
  Every refresh appends a new version; old estimates that captured a
  prior version replay against that historical snapshot exactly as
  they did the day they were generated.
- ``feed_runs``             — append-only execution log per Celery beat
  invocation (or manual admin trigger). Powers ``/admin/feeds`` status.
- ``price_anomaly_alerts``  — one row per >threshold% midpoint move.
  Slack notification is best-effort; the row is the audit record.

The ``live_price_quotes`` table reuses the Stage-0 convention columns
(versioning + soft-delete + effective dates + source) so it integrates
with ``BaseRepository._active_at`` without a single special case.

Revision ID: 0023_stage12_live_feeds
Revises: 0022_stage13_indexes
Create Date: 2026-05-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_stage12_live_feeds"
down_revision = "0022_stage13_indexes"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────
# Helpers (mirror 0002_stage1_pricing.py)
# ─────────────────────────────────────────────────────────────────────


def _convention_columns() -> list[sa.Column]:
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
    return [
        (f"ix_{table}_is_current", ["is_current"]),
        (f"ix_{table}_deleted_at", ["deleted_at"]),
        (f"ix_{table}_effective_from", ["effective_from"]),
        (f"ix_{table}_effective_to", ["effective_to"]),
        (f"ix_{table}_source", ["source"]),
        (f"ix_{table}_created_by", ["created_by"]),
    ]


def _audit_columns() -> list[sa.Column]:
    """Trimmed column set for tables that are append-only (no versioning)."""
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
    ]


# ─────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # ── live_price_quotes ────────────────────────────────────────────
    op.create_table(
        "live_price_quotes",
        *_convention_columns(),
        sa.Column("feed_source", sa.String(64), nullable=False),
        sa.Column("commodity_key", sa.String(160), nullable=False),
        sa.Column("material_slug", sa.String(120), nullable=True),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("basis_unit", sa.String(32), nullable=False),
        sa.Column("price_low", sa.Float(), nullable=False),
        sa.Column("price_high", sa.Float(), nullable=False),
        sa.Column(
            "currency",
            sa.String(8),
            nullable=False,
            server_default="INR",
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "freshness_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=str(24 * 3600),
        ),
        sa.CheckConstraint(
            "price_low >= 0 AND price_high >= price_low",
            name="ck_live_price_quotes_price_band",
        ),
    )
    op.create_index(
        "uq_live_price_quotes_logical_current",
        "live_price_quotes",
        ["feed_source", "commodity_key"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_live_price_quotes_material_slug",
        "live_price_quotes",
        ["material_slug"],
        postgresql_where=sa.text(
            "is_current = TRUE AND deleted_at IS NULL "
            "AND material_slug IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_live_price_quotes_feed_source",
        "live_price_quotes",
        ["feed_source"],
    )
    op.create_index(
        "ix_live_price_quotes_captured_at",
        "live_price_quotes",
        ["captured_at"],
    )
    for name, cols in _common_indexes("live_price_quotes"):
        op.create_index(name, "live_price_quotes", cols)

    # ── feed_runs ────────────────────────────────────────────────────
    op.create_table(
        "feed_runs",
        *_audit_columns(),
        sa.Column("feed_source", sa.String(64), nullable=False),
        sa.Column(
            "trigger",
            sa.String(32),
            nullable=False,
            server_default="beat",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "quotes_fetched",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "quotes_inserted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "quotes_skipped",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "anomalies_detected",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "error_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("actor_id", sa.String(32), nullable=True),
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'failure', 'skipped')",
            name="ck_feed_runs_status_enum",
        ),
    )
    op.create_index(
        "ix_feed_runs_feed_recent",
        "feed_runs",
        ["feed_source", "started_at"],
    )
    op.create_index("ix_feed_runs_status", "feed_runs", ["status"])

    # ── price_anomaly_alerts ─────────────────────────────────────────
    op.create_table(
        "price_anomaly_alerts",
        *_audit_columns(),
        sa.Column("feed_source", sa.String(64), nullable=False),
        sa.Column("commodity_key", sa.String(160), nullable=False),
        sa.Column("material_slug", sa.String(120), nullable=True),
        sa.Column("previous_price_mid", sa.Float(), nullable=False),
        sa.Column("new_price_mid", sa.Float(), nullable=False),
        sa.Column("pct_change", sa.Float(), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column(
            "feed_run_id",
            sa.String(32),
            sa.ForeignKey("feed_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "new_quote_id",
            sa.String(32),
            sa.ForeignKey("live_price_quotes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "notified_channel",
            sa.String(32),
            nullable=False,
            server_default="none",
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(32), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.CheckConstraint(
            "direction IN ('up', 'down')",
            name="ck_price_anomaly_alerts_direction_enum",
        ),
    )
    op.create_index(
        "ix_price_anomaly_alerts_feed_recent",
        "price_anomaly_alerts",
        ["feed_source", "created_at"],
    )
    op.create_index(
        "ix_price_anomaly_alerts_unack",
        "price_anomaly_alerts",
        ["acknowledged_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_anomaly_alerts_unack",
        table_name="price_anomaly_alerts",
    )
    op.drop_index(
        "ix_price_anomaly_alerts_feed_recent",
        table_name="price_anomaly_alerts",
    )
    op.drop_table("price_anomaly_alerts")

    op.drop_index("ix_feed_runs_status", table_name="feed_runs")
    op.drop_index("ix_feed_runs_feed_recent", table_name="feed_runs")
    op.drop_table("feed_runs")

    for name, _ in _common_indexes("live_price_quotes"):
        op.drop_index(name, table_name="live_price_quotes")
    op.drop_index(
        "ix_live_price_quotes_captured_at",
        table_name="live_price_quotes",
    )
    op.drop_index(
        "ix_live_price_quotes_feed_source",
        table_name="live_price_quotes",
    )
    op.drop_index(
        "ix_live_price_quotes_material_slug",
        table_name="live_price_quotes",
    )
    op.drop_index(
        "uq_live_price_quotes_logical_current",
        table_name="live_price_quotes",
    )
    op.drop_table("live_price_quotes")
