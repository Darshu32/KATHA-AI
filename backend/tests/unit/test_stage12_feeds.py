"""Stage 12 unit tests — live data feeds framework.

Covers the pure-logic primitives that don't need a DB or network:

- Anomaly detector: threshold default, custom threshold, no-previous,
  flat / up / down direction, zero-baseline edge case.
- Freshness classifier: every band, ``UNKNOWN`` for null captured_at,
  ``humanize_age`` rendering.
- Adapter contract: ``FeedQuote`` validation, stub adapters return
  the expected commodities, ``FeedRegistry`` registration + lookup.
- Slack formatter: payload shape (no actual webhook hit).

All in-process, no DB, no Redis, no real network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.feeds import FreshnessLevel, classify_freshness
from app.feeds.adapters import asian_paints, fx, gst, jaquar, kohler, mcx
from app.feeds.anomaly import AnomalyVerdict, detect_anomaly, midpoint
from app.feeds.base import AdapterError, FeedQuote, FetchOutcome
from app.feeds.freshness import freshness_envelope, humanize_age, seconds_since
from app.feeds.registry import (
    FeedRegistry,
    get_registry,
    register_for_test,
    reset_registry,
)
from app.feeds.slack import _format_message


# ─────────────────────────────────────────────────────────────────────
# Anomaly detector
# ─────────────────────────────────────────────────────────────────────


def test_anomaly_below_threshold_is_not_triggered():
    verdict = detect_anomaly(
        previous_low=100, previous_high=120,
        new_low=105, new_high=125,
        threshold_pct=10.0,
    )
    assert isinstance(verdict, AnomalyVerdict)
    assert verdict.triggered is False
    assert verdict.direction == "up"
    assert verdict.previous_mid == 110
    assert verdict.new_mid == 115


def test_anomaly_at_or_above_threshold_triggers():
    verdict = detect_anomaly(
        previous_low=100, previous_high=100,
        new_low=110, new_high=110,
        threshold_pct=10.0,
    )
    assert verdict.triggered is True
    assert verdict.direction == "up"
    assert verdict.pct_change == pytest.approx(10.0)


def test_anomaly_negative_move_is_down():
    verdict = detect_anomaly(
        previous_low=100, previous_high=100,
        new_low=80, new_high=80,
        threshold_pct=10.0,
    )
    assert verdict.triggered is True
    assert verdict.direction == "down"
    assert verdict.pct_change == pytest.approx(-20.0)


def test_anomaly_no_previous_quote_returns_flat_not_triggered():
    verdict = detect_anomaly(
        previous_low=None, previous_high=None,
        new_low=50, new_high=70,
    )
    assert verdict.triggered is False
    assert verdict.direction == "flat"
    assert verdict.reason == "no_previous_quote"


def test_anomaly_zero_previous_mid_does_not_trigger_div_by_zero():
    verdict = detect_anomaly(
        previous_low=0, previous_high=0,
        new_low=10, new_high=10,
    )
    assert verdict.triggered is False
    assert verdict.reason == "previous_mid_zero"


def test_anomaly_uses_settings_threshold_when_unspecified():
    s = get_settings()
    s.feed_anomaly_pct_threshold  # ensure attribute exists
    verdict = detect_anomaly(
        previous_low=100, previous_high=100,
        new_low=109, new_high=109,
    )
    assert verdict.threshold_pct == s.feed_anomaly_pct_threshold


def test_midpoint_helper():
    assert midpoint(10, 20) == 15.0
    assert midpoint(0, 0) == 0.0


# ─────────────────────────────────────────────────────────────────────
# Freshness classifier
# ─────────────────────────────────────────────────────────────────────


def test_freshness_unknown_when_no_captured_at():
    assert classify_freshness(None) == FreshnessLevel.UNKNOWN


def test_freshness_live_when_minutes_old():
    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert classify_freshness(when) == FreshnessLevel.LIVE


def test_freshness_recent_when_half_a_day_old():
    when = datetime.now(timezone.utc) - timedelta(hours=12)
    assert classify_freshness(when) == FreshnessLevel.RECENT


def test_freshness_stale_when_a_few_days_old():
    when = datetime.now(timezone.utc) - timedelta(days=3)
    assert classify_freshness(when) == FreshnessLevel.STALE


def test_freshness_expired_past_stale_band():
    when = datetime.now(timezone.utc) - timedelta(days=30)
    assert classify_freshness(when) == FreshnessLevel.EXPIRED


def test_freshness_expired_is_not_acceptable_for_live_lookup():
    assert FreshnessLevel.EXPIRED.is_acceptable_for_live_lookup is False
    assert FreshnessLevel.UNKNOWN.is_acceptable_for_live_lookup is False
    assert FreshnessLevel.LIVE.is_acceptable_for_live_lookup is True
    assert FreshnessLevel.STALE.is_acceptable_for_live_lookup is True


def test_humanize_age_buckets():
    now = datetime.now(timezone.utc)
    assert humanize_age(None) == "unknown"
    assert humanize_age(now - timedelta(seconds=30)).endswith("sec ago")
    assert humanize_age(now - timedelta(minutes=10)).endswith("min ago")
    assert humanize_age(now - timedelta(hours=3)).endswith("hrs ago")
    assert humanize_age(now - timedelta(days=5)).endswith("days ago")


def test_freshness_envelope_shape():
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    env = freshness_envelope(when)
    assert env["level"] in {"live", "recent"}
    assert env["age_human"].endswith("hrs ago") or env["age_human"].endswith("min ago")
    assert env["captured_at"]
    assert isinstance(env["age_seconds"], float)


def test_seconds_since_handles_naive_datetime():
    naive = datetime.utcnow() - timedelta(minutes=1)
    age = seconds_since(naive)
    assert age is not None and age > 0


# ─────────────────────────────────────────────────────────────────────
# FeedQuote validation
# ─────────────────────────────────────────────────────────────────────


def test_feed_quote_rejects_negative_price_low():
    with pytest.raises(AdapterError):
        FeedQuote(
            feed_source="x", commodity_key="y", display_name="z",
            basis_unit="kg", price_low=-1, price_high=10,
            captured_at=datetime.now(timezone.utc),
        )


def test_feed_quote_rejects_inverted_band():
    with pytest.raises(AdapterError):
        FeedQuote(
            feed_source="x", commodity_key="y", display_name="z",
            basis_unit="kg", price_low=20, price_high=10,
            captured_at=datetime.now(timezone.utc),
        )


def test_feed_quote_accepts_equal_low_high():
    q = FeedQuote(
        feed_source="x", commodity_key="y", display_name="z",
        basis_unit="rate", price_low=83.22, price_high=83.22,
        captured_at=datetime.now(timezone.utc),
    )
    assert q.price_low == q.price_high


# ─────────────────────────────────────────────────────────────────────
# Stub adapters
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcx_stub_returns_three_metals():
    adapter = mcx.StubAdapter(get_settings())
    outcome = await adapter.fetch()
    assert outcome.status == "success"
    keys = sorted(q.commodity_key for q in outcome.quotes)
    assert keys == ["aluminium", "copper", "steel_hrc"]
    # Every commodity that maps to a seeded material slug carries the
    # link; copper currently stands alone because no copper material
    # seed exists yet.
    by_key = {q.commodity_key: q for q in outcome.quotes}
    assert by_key["steel_hrc"].material_slug == "mild_steel"
    assert by_key["aluminium"].material_slug == "aluminium_6061"
    assert by_key["copper"].material_slug is None


@pytest.mark.asyncio
async def test_fx_stub_returns_two_pairs():
    adapter = fx.StubAdapter(get_settings())
    outcome = await adapter.fetch()
    assert outcome.status == "success"
    keys = sorted(q.commodity_key for q in outcome.quotes)
    assert keys == ["eur_inr", "usd_inr"]


@pytest.mark.asyncio
async def test_gst_stub_returns_six_hsn_codes():
    adapter = gst.StubAdapter(get_settings())
    outcome = await adapter.fetch()
    assert outcome.status == "success"
    assert len(outcome.quotes) == 6
    for q in outcome.quotes:
        assert q.basis_unit == "pct"


@pytest.mark.asyncio
async def test_vendor_stubs_return_catalog_skus():
    s = get_settings()
    for module in (jaquar, kohler, asian_paints):
        adapter = module.StubAdapter(s)
        outcome = await adapter.fetch()
        assert outcome.status == "success"
        assert outcome.quotes
        for q in outcome.quotes:
            assert q.feed_source == module.StubAdapter.feed_source


@pytest.mark.asyncio
async def test_live_adapter_returns_failure_when_url_unset():
    """LiveAdapter SHOULD NOT raise — return failure outcome."""
    adapter = mcx.LiveAdapter(get_settings())
    outcome = await adapter.fetch()
    assert outcome.status == "failure"
    assert "feed_mcx_base_url" in (outcome.error or "")


# ─────────────────────────────────────────────────────────────────────
# FeedRegistry
# ─────────────────────────────────────────────────────────────────────


def test_registry_register_and_lookup():
    reg = FeedRegistry()
    s = get_settings()
    a = mcx.StubAdapter(s)
    reg.register(a)
    assert reg.get("mcx") is a
    assert reg.feed_sources() == ["mcx"]
    reg.unregister("mcx")
    assert reg.get("mcx") is None


def test_register_for_test_replaces_singleton():
    s = get_settings()
    register_for_test([mcx.StubAdapter(s)])
    try:
        assert get_registry().feed_sources() == ["mcx"]
    finally:
        reset_registry()


def test_default_registry_has_six_adapters():
    reset_registry()
    try:
        reg = get_registry()
        assert sorted(reg.feed_sources()) == [
            "fx_rbi",
            "gst_cbic",
            "mcx",
            "vendor:asian_paints",
            "vendor:jaquar",
            "vendor:kohler",
        ]
    finally:
        reset_registry()


# ─────────────────────────────────────────────────────────────────────
# Slack formatter
# ─────────────────────────────────────────────────────────────────────


def test_slack_format_includes_pct_and_blocks():
    msg = _format_message(
        feed_source="mcx",
        commodity_key="steel_hrc",
        previous_mid=100.0,
        new_mid=120.0,
        pct_change=20.0,
        threshold_pct=10.0,
        direction="up",
        material_slug="mild_steel",
    )
    assert "Price anomaly" in msg["text"]
    assert "steel_hrc" in msg["text"]
    assert msg["blocks"]
    assert any("20.00%" in str(b) for b in msg["blocks"])
    assert any("mild_steel" in str(b) for b in msg["blocks"])


def test_slack_format_handles_negative_move():
    msg = _format_message(
        feed_source="vendor:jaquar",
        commodity_key="JAQ-FAU-001",
        previous_mid=10000.0,
        new_mid=8500.0,
        pct_change=-15.0,
        threshold_pct=10.0,
        direction="down",
    )
    assert "(down)" in msg["text"]


# ─────────────────────────────────────────────────────────────────────
# FetchOutcome convenience
# ─────────────────────────────────────────────────────────────────────


def test_fetch_outcome_ok_property():
    assert FetchOutcome(status="success").ok is True
    assert FetchOutcome(status="partial").ok is True
    assert FetchOutcome(status="failure").ok is False
    assert FetchOutcome(status="skipped").ok is False
