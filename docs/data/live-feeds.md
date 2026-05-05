# Stage 12 — Live Data Feeds

> **Audience:** ops + future-you wiring upstream price sources to the
> cost engine. Read after `docs/data/pricing.md`.

---

## What it does

Self-updating market data so prices stay current without human
intervention. The cost engine continues to read versioned rows from
Postgres exactly as it has since Stage 1 — the difference is that
the rows are now appended by **scheduled adapters** (MCX, FX, GST,
vendor scrapers) instead of by `alembic` migrations alone.

The Stage 1 reproducibility guarantee is preserved: every refresh
appends a *new version* of the affected logical row, the previous
version is demoted to `is_current=false`, and any pricing snapshot
captured before the refresh continues to point at the historical
version it saw.

```
                ┌──────────────┐
   Celery beat ─▶  feed_tasks  ─┐
                └──────────────┘ │
                                 ▼
                       ┌─────────────────────┐
                       │ app.feeds.service   │  one transaction per refresh
                       │   .run_feed(source) │  + audit row in feed_runs
                       └─────────┬───────────┘
                                 │
                ┌──────────────┐ │ ┌──────────────────┐
                │  Adapter     │◀┴▶│ LivePriceQuote   │   versioned per
                │  .fetch()    │   │ Repository       │   (feed_source,
                │              │   │  .upsert_quote() │    commodity_key)
                └──────┬───────┘   └──────────────────┘
                       │
                       ▼ +Δ% ≥ threshold
              ┌─────────────────────┐    Slack (best-effort)
              │ PriceAnomalyAlert   │ ──▶ #price-alerts
              └─────────────────────┘
```

---

## The three new tables

| Table | What it holds | Versioning |
|---|---|---|
| `live_price_quotes` | One row per `(feed_source, commodity_key)` per refresh; reused by the fallback chain to override seed prices | Yes (Stage-0 mixins) |
| `feed_runs` | One row per Celery beat or manual refresh — duration, status, counts, error payload | Append-only |
| `price_anomaly_alerts` | One row per >threshold% midpoint move; Slack ping is best-effort, the row is the audit record | Append-only |

Migration: `alembic/versions/0023_stage12_live_feeds.py`.

---

## The bundled adapters

| feed_source | Cadence (beat) | TTL | What it pulls |
|---|---|---|---|
| `mcx` | Every 6h | 24h | Steel HRC, primary aluminium, copper |
| `fx_rbi` | Every 6h | 24h | USD/INR, EUR/INR |
| `gst_cbic` | Weekly | 30d | HSN-coded GST rates (timber, metals, ceramics, sanitaryware, paint, fabrics) |
| `vendor:jaquar` | Daily | 7d | Premium sanitaryware SKUs |
| `vendor:kohler` | Daily | 7d | Premium kitchen + bath SKUs |
| `vendor:asian_paints` | Daily | 7d | Decorative + protective finishes per litre |

Every adapter ships in **two modes**: `LiveAdapter` (HTTP, parses
upstream payload) and `StubAdapter` (deterministic offline fixtures
for tests + dev). Selection is driven by
`settings.live_feeds_enabled`; per-feed env flags layer on top so
ops can disable a single noisy scraper without taking the whole
feed loop down.

---

## Configuration

All live-feed knobs live in `app/config.py` under the
"Stage 12 — Live data feeds" section:

```python
live_feeds_enabled: bool = False  # master kill-switch
feed_mcx_enabled: bool = True
feed_fx_enabled: bool = True
feed_gst_enabled: bool = True
feed_vendor_jaquar_enabled: bool = True
feed_vendor_kohler_enabled: bool = True
feed_vendor_asian_paints_enabled: bool = True

feed_http_timeout_seconds: float = 20.0
feed_http_max_retries: int = 2

feed_anomaly_pct_threshold: float = 10.0  # >= this fires an alert
feed_slack_webhook_url: str = ""           # empty = log-only fallback
feed_slack_channel: str = "#price-alerts"

feed_freshness_live_seconds: int = 6 * 3600
feed_freshness_recent_seconds: int = 24 * 3600
feed_freshness_stale_seconds: int = 14 * 86400

feed_mcx_base_url: str = ""    # ops-configured
feed_fx_base_url: str = ""
feed_gst_base_url: str = ""
```

Defaults are safe (master switch OFF; tests + dev get stubs).
Production deploy:

1. Set `LIVE_FEEDS_ENABLED=true`
2. Set `FEED_MCX_BASE_URL`, `FEED_FX_BASE_URL`, `FEED_GST_BASE_URL`
3. Set `FEED_SLACK_WEBHOOK_URL` (optional but recommended)

---

## Fallback chain

`app/feeds/fallback.py::resolve_price_for_material` is the single
entry point the cost engine uses. It walks a strict order:

```
   ┌──────────┐    fresh ≤ recent       ┌──────────┐
   │  live    │──────────────────────▶ │  use it  │ tier=live
   │ quote?   │
   │          │    fresh = stale        ┌──────────┐
   │          │──────────────────────▶ │  use it  │ tier=cached
   │          │
   │          │    fresh = expired ─▶  fall through
   └──────────┘
        │
        ▼
   ┌──────────┐    yes        ┌──────────┐
   │  seed    │──────────────▶│  use it  │ tier=seed
   │ row?     │               └──────────┘
   └──────────┘
        │
        ▼
   ┌──────────────────────────┐
   │  unavailable             │ tier=unavailable
   │  (caller renders badge)  │
   └──────────────────────────┘
```

The resolved tier + freshness envelope lands in the cost-engine
snapshot's `source_versions.materials.{slug}` block:

```json
{
  "tier": "live",
  "freshness": {
    "level": "live",
    "age_seconds": 7200,
    "age_human": "2 hrs ago",
    "captured_at": "2026-05-02T08:00:00+00:00"
  },
  "source": "mcx",
  "quote_id": "ab12cd34..."
}
```

The Stage 11 transparency banner reads these and renders the
"Last priced: 2 hrs ago" badge on every estimate.

---

## Anomaly detection

`app/feeds/anomaly.py::detect_anomaly` is pure — no DB, no IO. It
compares the previous-current quote's midpoint against the new
quote's midpoint and fires when `|pct_change| ≥ threshold` (default
10%, configurable per call or via settings).

Primary use case: **catching API errors** (an upstream that returns
1/100th of the real value, a scraper that picked up a sale price).
Secondary: real-world price spikes that ops wants to know about.

When triggered:
1. The quote is still persisted (anomalies are advisory).
2. A `price_anomaly_alerts` row is written.
3. Slack is poked (best-effort) with a Block-Kit message.
4. The alert id is queued to `/admin/feeds/alerts` for ops to
   acknowledge.

If the Slack webhook is unset, the alert is logged at WARNING and
the row's `notified_channel` is set to `"log"` — no exception,
no Celery retry storm.

---

## Admin API

```
GET  /api/v1/admin/feeds                                     dashboard
GET  /api/v1/admin/feeds/{source}/quotes                     current rows
GET  /api/v1/admin/feeds/{source}/quotes/{commodity}/history all versions
GET  /api/v1/admin/feeds/{source}/runs                       run history
POST /api/v1/admin/feeds/{source}/refresh   {"force": false} manual trigger
GET  /api/v1/admin/feeds/alerts                              alerts
POST /api/v1/admin/feeds/alerts/{id}/ack                     ack an alert
```

`force=true` overrides the per-feed enable flag for a single run.
The master `live_feeds_enabled` switch is **not** overridable —
ops keep the global kill-switch.

---

## Test gate (BRD)

The Stage 12 BRD test gate is implemented in
`tests/integration/test_stage12_feeds.py::test_disable_feed_then_reenable_resumes`:

1. Master switch ON, per-feed flag OFF →
   `run_feed("mcx")` returns `status="skipped"`, no quotes written.
2. Re-enable per-feed flag → next call returns `status="success"`,
   quote rows appear.

The fallback chain is independently exercised by
`test_fallback_uses_seed_when_no_live_quote` and
`test_fallback_uses_live_when_available`.

---

## Adding a new adapter

1. Drop a module under `app/feeds/adapters/`.
2. Define `LiveAdapter` + `StubAdapter` subclasses of
   :class:`app.feeds.base.FeedAdapter`. Each implements
   `async def fetch() -> FetchOutcome`.
3. Expose `build_adapter(settings, *, live: bool) -> FeedAdapter`.
4. Add the import to
   `app.feeds.registry._bootstrap_default_adapters`.
5. Add a beat schedule entry in `app/workers/celery_app.py`.
6. Add a per-feed enable flag to `app/config.py` and the
   `_is_feed_enabled` map in `app/feeds/service.py`.
7. Mirror the pattern with at least one stub-mode unit test in
   `tests/unit/test_stage12_feeds.py`.

The vendor scrapers inherit from `_vendor.VendorLiveAdapter`/
`VendorStubAdapter` so the SKU catalog is the only per-vendor delta.

---

## What this stage does NOT change

- The cost-engine prompt — same dict shape; new metadata is
  additive in `source_versions`.
- The Stage 1 `PricingSnapshot` table — snapshots taken before
  Stage 12 continue to replay against historical seed rows;
  snapshots taken after Stage 12 replay against historical live
  quotes when present.
- The Stage 11 transparency banner contract — `freshness` is
  appended to the `source_versions.materials.{slug}` dict as a
  new optional field; legacy clients that ignore it are unaffected.

---

## ADR-style summary

- **What:** scheduled HTTP adapters refresh `live_price_quotes`
  on cadence; cost engine prefers live → cached → seed.
- **Why:** the BRD calls for "fresh data daily, no manual price
  updates"; before Stage 12 every price change was a migration.
- **Trade-offs:** vendor scrapers are inherently brittle; we ship
  the stub variant alongside the live variant so a parser break
  degrades to "stale data + ops alert" rather than "API outage".
- **Reversibility:** flip `LIVE_FEEDS_ENABLED=false` and the
  cost engine reverts to seed-only behaviour with no code change.
