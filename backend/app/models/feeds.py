"""Stage 12 — live data feeds ORM models.

Three tables, one purpose: keep the cost engine's prices fresh
without losing the Stage 1 reproducibility guarantee.

- ``LivePriceQuote``      : current + historical readings from any
  external feed (MCX, FX, GST, vendor scrapers). Versioned per
  ``(feed_source, commodity_key)`` so reproducing yesterday's
  estimate still finds yesterday's quote even after today's refresh.
- ``FeedRun``             : append-only execution log per Celery beat
  invocation. Powers the admin "last refresh" dashboard and the
  ``/admin/feeds`` status endpoint.
- ``PriceAnomalyAlert``   : one row per >threshold% midpoint move
  detected by :func:`app.feeds.anomaly.detect_anomaly`. Slack
  notification is best-effort; the row is the source of truth.

All three play nicely with the Stage 1 + Stage 11 plumbing — every
quote carries ``source`` + ``source_ref`` so the reasoning-transparency
banner can cite "MCX 2026-05-02 14:30 IST" instead of "internal seed".
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
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


# ─────────────────────────────────────────────────────────────────────
# Live price quotes
# ─────────────────────────────────────────────────────────────────────


class LivePriceQuote(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    VersionedMixin,
    EffectiveDatesMixin,
    SourceMixin,
    ActorMixin,
):
    """A single price reading from an external feed.

    Logical key: ``(feed_source, commodity_key)``. ``feed_source`` is
    the adapter name (``mcx``, ``fx_rbi``, ``vendor:jaquar``);
    ``commodity_key`` is the natural identifier within that feed —
    e.g. ``steel_hrc`` for MCX, ``usd_inr`` for FX, ``JAQ-FAU-001``
    for a Jaquar SKU.

    The price is stored as a band ``[price_low, price_high]`` for
    parity with :class:`MaterialPrice`. Single-point feeds (FX rates,
    GST percentages) collapse the band to ``low == high``.

    ``material_slug`` is an optional string-link into
    ``material_prices.slug``. When populated, the fallback chain
    (:func:`app.feeds.fallback.resolve_price`) prefers this quote
    over the seed row at lookup time.
    """

    __tablename__ = "live_price_quotes"
    __table_args__ = (
        Index(
            "uq_live_price_quotes_logical_current",
            "feed_source",
            "commodity_key",
            unique=True,
            postgresql_where=text("is_current = TRUE AND deleted_at IS NULL"),
        ),
        Index(
            "ix_live_price_quotes_material_slug",
            "material_slug",
            postgresql_where=text(
                "is_current = TRUE AND deleted_at IS NULL "
                "AND material_slug IS NOT NULL"
            ),
        ),
        Index("ix_live_price_quotes_feed_source", "feed_source"),
        Index("ix_live_price_quotes_captured_at", "captured_at"),
    )

    feed_source: Mapped[str] = mapped_column(String(64), nullable=False)
    commodity_key: Mapped[str] = mapped_column(String(160), nullable=False)

    material_slug: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )

    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    basis_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    price_low: Mapped[float] = mapped_column(Float, nullable=False)
    price_high: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="INR"
    )

    # When the upstream feed observed this price (NOT when we wrote
    # the row). Drives freshness classification.
    captured_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    freshness_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24 * 3600
    )


# ─────────────────────────────────────────────────────────────────────
# Feed runs (execution history)
# ─────────────────────────────────────────────────────────────────────


class FeedRun(Base, UUIDMixin, TimestampMixin):
    """Append-only execution log for a single feed refresh.

    One row per Celery beat invocation OR per manual admin trigger.
    Never updated after insert (no ``VersionedMixin`` /
    ``SoftDeleteMixin``); rows older than the operations retention
    window are pruned by a separate housekeeping task.

    ``status`` semantics:
      - ``success``  : every commodity persisted, no errors.
      - ``partial``  : some commodities persisted, some failed
        (per-commodity errors recorded inside ``error_payload``).
      - ``failure``  : adapter raised before any commodity was
        persisted (auth failure, network down, parse error).
      - ``skipped``  : feed disabled by env flag — recorded so
        ops dashboards stay accurate.
    """

    __tablename__ = "feed_runs"
    __table_args__ = (
        Index("ix_feed_runs_feed_recent", "feed_source", "started_at"),
        Index("ix_feed_runs_status", "status"),
        CheckConstraint(
            "status IN ('success', 'partial', 'failure', 'skipped')",
            name="ck_feed_runs_status_enum",
        ),
    )

    feed_source: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(
        String(32), nullable=False, default="beat"
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    quotes_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quotes_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quotes_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    anomalies_detected: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )


# ─────────────────────────────────────────────────────────────────────
# Anomaly alerts
# ─────────────────────────────────────────────────────────────────────


class PriceAnomalyAlert(Base, UUIDMixin, TimestampMixin):
    """A >threshold% midpoint move detected during a feed refresh.

    Alerts are *advisory* — they do not block the new quote from
    being persisted. Catching API errors (e.g. an MCX page returning
    1/100th of the real value) is the primary use case; a real-world
    price spike is the secondary one.

    ``notified_at`` is set after a successful Slack POST; remains
    null when the webhook is unconfigured or the POST failed
    (the row is still useful as the audit record).
    """

    __tablename__ = "price_anomaly_alerts"
    __table_args__ = (
        Index(
            "ix_price_anomaly_alerts_feed_recent",
            "feed_source",
            "created_at",
        ),
        Index(
            "ix_price_anomaly_alerts_unack",
            "acknowledged_at",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )

    feed_source: Mapped[str] = mapped_column(String(64), nullable=False)
    commodity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    material_slug: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )

    previous_price_mid: Mapped[float] = mapped_column(Float, nullable=False)
    new_price_mid: Mapped[float] = mapped_column(Float, nullable=False)
    pct_change: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_pct: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)

    feed_run_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("feed_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    new_quote_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("live_price_quotes.id", ondelete="SET NULL"),
        nullable=True,
    )

    notified_channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none"
    )
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notification_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
