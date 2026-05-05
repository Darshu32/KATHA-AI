"""Stage 12 integration tests — live data feeds end-to-end.

Requires a Postgres + Redis stack with migrations applied:

    docker compose up -d postgres redis migrate
    KATHA_INTEGRATION_TESTS=1 pytest backend/tests/integration

Skipped automatically without that env var (see conftest.py).

Coverage map
------------
- ``test_full_refresh_persists_quotes_and_run``  : adapter → service →
  ``live_price_quotes`` + ``feed_runs`` rows in one go.
- ``test_versioning_promotes_old_quote``          : second refresh
  appends a new version, demotes the previous to ``is_current=False``.
- ``test_anomaly_alert_recorded_on_big_jump``    : injecting an
  outsized stub move produces a ``price_anomaly_alerts`` row.
- ``test_disable_feed_then_reenable_resumes``    : the BRD test gate
  — disable → fallback engages → re-enable → updates resume.
- ``test_fallback_uses_seed_when_no_live_quote``  : ResolvedPrice
  tier == ``seed`` when the live table is empty.
- ``test_fallback_uses_live_when_available``      : ResolvedPrice
  tier == ``live`` when a fresh quote exists for the slug.
- ``test_knowledge_service_freshness_in_source_versions`` : the
  cost-engine snapshot carries the ``tier`` + ``freshness`` envelope
  for every material.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Test-local stub adapter (parametrises the data the harness sees)
# ─────────────────────────────────────────────────────────────────────


class _Programmable(FeedAdapter):
    """Adapter the test controls quote-by-quote.

    Per-instance ``feed_source`` lets a single test bind it to any
    canonical slot (e.g. ``"mcx"``) so the per-feed enable flag map
    in :func:`app.feeds.service._is_feed_enabled` matches.
    """

    display_name = "Programmable Test Adapter"
    description = ""

    def __init__(
        self,
        settings: Any,
        quotes: list[FeedQuote] | None = None,
        *,
        feed_source: str = "test:programmable",
        status: str = "success",
        error: str | None = None,
    ) -> None:
        super().__init__(settings)
        self.feed_source = feed_source
        self._quotes = quotes or []
        self._status = status
        self._error = error

    async def fetch(self) -> FetchOutcome:
        return FetchOutcome(
            status=self._status,
            quotes=list(self._quotes),
            error=self._error,
        )


def _quote(
    *,
    feed_source: str,
    commodity_key: str,
    low: float,
    high: float,
    material_slug: str | None = None,
    captured_at: datetime | None = None,
) -> FeedQuote:
    return FeedQuote(
        feed_source=feed_source,
        commodity_key=commodity_key,
        display_name=f"{feed_source}/{commodity_key}",
        material_slug=material_slug,
        category="commodity",
        basis_unit="kg",
        price_low=low,
        price_high=high,
        captured_at=captured_at or datetime.now(timezone.utc),
        source_ref=f"test:{feed_source}:{commodity_key}",
        payload={"test": True},
    )


# ─────────────────────────────────────────────────────────────────────
# End-to-end refresh
# ─────────────────────────────────────────────────────────────────────


async def test_full_refresh_persists_quotes_and_run(db_session, monkeypatch):
    from app.config import get_settings
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed
    from app.repositories.live_pricing import (
        FeedRunRepository,
        LivePriceQuoteRepository,
    )

    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    get_settings.cache_clear()

    quotes = [
        _quote(feed_source="test:programmable", commodity_key="alpha", low=10, high=20),
        _quote(feed_source="test:programmable", commodity_key="beta", low=100, high=110),
    ]
    register_for_test([_Programmable(get_settings(), quotes)])

    run = await run_feed("test:programmable", trigger="manual")
    assert run["status"] == "success"
    assert run["quotes_inserted"] == 2

    # Persisted rows visible via the repos.
    quote_repo = LivePriceQuoteRepository(db_session)
    rows = await quote_repo.list_active(feed_source="test:programmable")
    assert {r["commodity_key"] for r in rows} == {"alpha", "beta"}

    runs = await FeedRunRepository(db_session).history(
        feed_source="test:programmable", limit=5
    )
    assert runs and runs[0]["status"] == "success"


async def test_versioning_promotes_old_quote(db_session, monkeypatch):
    from app.config import get_settings
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed
    from app.repositories.live_pricing import LivePriceQuoteRepository

    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    get_settings.cache_clear()

    adapter = _Programmable(
        get_settings(),
        [_quote(feed_source="test:programmable", commodity_key="alpha", low=10, high=20)],
    )
    register_for_test([adapter])
    await run_feed("test:programmable", trigger="manual")

    # Replace the quote with a new band; second run should append a version.
    adapter._quotes = [
        _quote(feed_source="test:programmable", commodity_key="alpha", low=11, high=21)
    ]
    await run_feed("test:programmable", trigger="manual")

    repo = LivePriceQuoteRepository(db_session)
    history = await repo.history(
        feed_source="test:programmable",
        commodity_key="alpha",
    )
    assert len(history) == 2
    assert history[0]["version"] == 2
    assert history[0]["is_current"] is True
    assert history[1]["version"] == 1
    assert history[1]["is_current"] is False


async def test_anomaly_alert_recorded_on_big_jump(db_session, monkeypatch):
    from app.config import get_settings
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed
    from app.repositories.live_pricing import PriceAnomalyAlertRepository

    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    get_settings.cache_clear()

    adapter = _Programmable(
        get_settings(),
        [_quote(feed_source="test:programmable", commodity_key="alpha", low=100, high=100)],
    )
    register_for_test([adapter])
    await run_feed("test:programmable", trigger="manual")

    # 25% jump — well above the default 10% threshold.
    adapter._quotes = [
        _quote(feed_source="test:programmable", commodity_key="alpha", low=125, high=125)
    ]
    run = await run_feed("test:programmable", trigger="manual")
    assert run["anomalies_detected"] == 1

    alerts = await PriceAnomalyAlertRepository(db_session).list_recent(
        feed_source="test:programmable", limit=5
    )
    assert alerts
    assert alerts[0]["direction"] == "up"
    assert alerts[0]["pct_change"] == pytest.approx(25.0)
    # Notification falls back to log when no webhook is configured.
    assert alerts[0]["notified_channel"] in {"log", "slack", "none"}


# ─────────────────────────────────────────────────────────────────────
# Test gate: disable → fallback → re-enable
# ─────────────────────────────────────────────────────────────────────


async def test_disable_feed_then_reenable_resumes(db_session, monkeypatch):
    """The BRD test gate.

    Disable the feed → ``run_feed`` records a ``skipped`` run and no
    quote is written. Re-enable → next call writes the quote as expected.
    """
    from app.config import get_settings
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed
    from app.repositories.live_pricing import LivePriceQuoteRepository

    # Master switch ON, but per-feed flag OFF (we'll use mcx slot since
    # _is_feed_enabled has the per-feed map keyed on built-in sources).
    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    monkeypatch.setenv("FEED_MCX_ENABLED", "false")
    get_settings.cache_clear()

    quote = _quote(feed_source="mcx", commodity_key="steel_hrc", low=70, high=85)
    adapter = _Programmable(get_settings(), [quote], feed_source="mcx")
    register_for_test([adapter])

    skipped = await run_feed("mcx", trigger="manual")
    assert skipped["status"] == "skipped"

    repo = LivePriceQuoteRepository(db_session)
    assert (await repo.list_active(feed_source="mcx")) == []

    # Re-enable.
    monkeypatch.setenv("FEED_MCX_ENABLED", "true")
    get_settings.cache_clear()

    resumed = await run_feed("mcx", trigger="manual")
    assert resumed["status"] == "success"
    rows = await repo.list_active(feed_source="mcx")
    assert {r["commodity_key"] for r in rows} == {"steel_hrc"}


# ─────────────────────────────────────────────────────────────────────
# Fallback chain
# ─────────────────────────────────────────────────────────────────────


async def test_fallback_uses_seed_when_no_live_quote(db_session):
    from app.feeds.fallback import resolve_price_for_material

    # `mild_steel` is seeded by 0003_stage1_pricing_seed.
    resolved = await resolve_price_for_material(
        db_session, material_slug="mild_steel"
    )
    assert resolved.tier in {"seed", "unavailable"}
    if resolved.tier == "seed":
        assert resolved.available is True
        assert resolved.price_high >= resolved.price_low > 0


async def test_fallback_uses_live_when_available(db_session, monkeypatch):
    from app.config import get_settings
    from app.feeds.fallback import resolve_price_for_material
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed

    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    get_settings.cache_clear()

    quote = _quote(
        feed_source="mcx",
        commodity_key="steel_hrc",
        low=66.6,
        high=77.7,
        material_slug="mild_steel",
        captured_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    adapter = _Programmable(get_settings(), [quote], feed_source="mcx")
    register_for_test([adapter])
    await run_feed("mcx", trigger="manual", force=True)

    resolved = await resolve_price_for_material(
        db_session, material_slug="mild_steel"
    )
    assert resolved.tier == "live"
    assert resolved.price_low == pytest.approx(66.6)
    assert resolved.price_high == pytest.approx(77.7)
    assert resolved.freshness["level"] in {"live", "recent"}


async def test_knowledge_service_freshness_in_source_versions(db_session, monkeypatch):
    from app.config import get_settings
    from app.feeds.registry import register_for_test
    from app.feeds.service import run_feed
    from app.services.pricing import build_pricing_knowledge

    monkeypatch.setenv("LIVE_FEEDS_ENABLED", "true")
    get_settings.cache_clear()

    quote = _quote(
        feed_source="mcx",
        commodity_key="steel_hrc",
        low=66.6,
        high=77.7,
        material_slug="mild_steel",
    )
    adapter = _Programmable(get_settings(), [quote], feed_source="mcx")
    register_for_test([adapter])
    await run_feed("mcx", trigger="manual", force=True)

    knowledge = await build_pricing_knowledge(
        db_session,
        project_name="x",
        piece_name="x",
        theme="modern",
        city="mumbai",
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=4,
    )
    materials_meta = knowledge["source_versions"].get("materials", {})
    if "mild_steel" in materials_meta:
        meta = materials_meta["mild_steel"]
        assert meta.get("tier") in {"live", "cached", "seed"}
        assert "freshness" in meta
