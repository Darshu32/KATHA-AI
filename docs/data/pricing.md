# Stage 1 — Pricing Externalization

> **Audience:** future-you maintaining cost data and the agent layers
> built on top of it. Read after `docs/foundations.md`.

---

## What changed

Cost data that previously lived as Python literals in
`app/knowledge/costing.py`, `app/knowledge/regional_materials.py`, and
the cost-related fields of `app/knowledge/materials.py` is now stored
as **versioned, audited, time-bounded rows in Postgres**.

The cost engine (`app/services/cost_engine_service.py`) is the **only**
service migrated to the DB-backed path in Stage 1. Every other
consumer of the legacy modules continues to read from Python (until
Stage 3 migrates them).

---

## The six new tables

| Table | Logical key | What it holds |
|---|---|---|
| `material_prices` | `(slug, region)` | Per-material price band, basis unit, lead time, availability cities, extras (density, MOR, finish options …) |
| `labor_rates` | `(trade, region)` | Per-trade hourly rate band |
| `trade_hour_estimates` | `(trade, complexity)` | Hours-per-piece band for a given complexity |
| `city_price_indices` | `city_slug` | Regional cost multiplier + lead-time adders + aliases |
| `cost_factors` | `factor_key` | Generic key/value bands (waste %, finish %, overhead %, hardware ₹, etc.) |
| `pricing_snapshots` | `id` (append-only) | Immutable record of every dict the cost engine consumed |

### Convention columns (all six)

Every business-data row carries the Stage-0 mixin set:

```
id, created_at, updated_at,
deleted_at,
version, is_current, previous_version_id,
effective_from, effective_to,
source, source_ref,
created_by
```

Every versioned table additionally has a partial unique index:

```sql
CREATE UNIQUE INDEX uq_<table>_logical_current
  ON <table> (<logical_key>)
  WHERE is_current = TRUE AND deleted_at IS NULL;
```

This guarantees at most one current version per logical key, at the
DB level — application bugs can't silently produce duplicate winners.

---

## How the cost engine consumes it

```
                           ┌──────────────────────────────────┐
  POST /cost-engine ───►   │ generate_cost_engine(req,        │
                           │   session, snapshot_id?)         │
                           └──────────────┬───────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────────────┐
                            │ build_cost_engine_knowledge      │
                            │ (delegates to                    │
                            │  app.services.pricing            │
                            │  .build_pricing_knowledge)       │
                            └──────────┬───────────┬──────────┘
                                       │           │
                  ┌────────────────────┘           └────────────────┐
                  ▼                                                  ▼
   ┌───────────────────────────┐              ┌───────────────────────────────┐
   │ Repositories pull active  │              │ record_snapshot()             │
   │ rows by `effective_from <=│              │ inserts immutable             │
   │ when AND ... > when`       │              │ pricing_snapshots row         │
   └────────────┬──────────────┘              └────────────┬──────────────────┘
                │                                          │
                └──────────────┬───────────────────────────┘
                               ▼
                        cost_engine output
                        + pricing_snapshot_id
```

### Replay mode

```
POST /cost-engine?snapshot_id=<id>
   ↓
load_snapshot(session, snapshot_id)
   ↓
LLM sees the EXACT dict captured before — no DB reads, no drift.
```

This is what makes "old estimates reproduce identically" true even
after admin price updates.

---

## How to update a price

Never edit the Python files. Use the admin endpoints — they version,
audit, and invalidate caches in one call.

```bash
# Update walnut price in global region
curl -X POST /admin/pricing/materials/walnut \
  -H "Content-Type: application/json" \
  -d '{"new_low": 520, "new_high": 820, "reason": "May 2026 vendor sheet"}'

# Update a city multiplier
curl -X POST /admin/pricing/cities/mumbai \
  -d '{"new_multiplier": 1.22, "reason": "Cement spike"}'

# Update a BRD constant
curl -X POST /admin/pricing/factors/waste_factor_pct \
  -d '{"new_low": 12, "new_high": 18, "reason": "Q2 2026 calibration"}'

# Read full version history of an entity
GET /admin/pricing/materials/walnut/history
GET /admin/pricing/cities/mumbai/history
GET /admin/pricing/factors/waste_factor_pct/history
```

Every write:
1. Demotes the old row (`is_current=False`, `effective_to=now`).
2. Inserts a new row (`version+1`, `is_current=True`, `effective_from=now`).
3. Records an `AuditEvent` with full before/after diff + actor +
   `reason` + `request_id`.

Cache invalidation: Stage 1 doesn't cache repository reads at the repo
layer. Stage 2 (when the agent loop materialises) introduces a
`@async_cached(namespace="pricing", ttl=300)` wrapper around the
top-level `build_pricing_knowledge` call, with explicit invalidation
on every admin write.

---

## Source tags (provenance)

Every row carries a `source` tag. Conventions:

| Tag prefix | Meaning |
|---|---|
| `seed:<module>.<symbol>` | Loaded from a legacy Python literal at migration time |
| `admin` | Created via the admin REST endpoint |
| `scraper:<integration>` | Pulled by Stage 12 live data feed (e.g. `scraper:mcx`) |
| `vendor:<brand>` | Imported from a vendor catalogue |
| `rag:<doc>` | Extracted from a knowledge document |

`build_pricing_knowledge()` returns a `source_versions` block listing
every row id + version + source tag that contributed to the dict.
Stage 11 (transparency) renders this as the "where did this number
come from?" UI.

---

## Snapshot lifecycle

```
   Estimate created
         │
         ├─► record_snapshot(...)  ───► pricing_snapshots row
         │                                       │
         │                                       │
   Admin updates walnut                          │
         │                                       │  (snapshot data is
         ▼                                       │   unchanged — that's
   New material_prices row (version 2)           │   the whole point)
                                                 │
   Estimate re-fetched                           │
         │                                       │
         ├─► load_snapshot(snapshot_id) ◄────────┘
         │
         └─► LLM run with original dict → same numbers
```

**Snapshots are never updated.** No `version` column, no
`SoftDeleteMixin`. If you discover a bug in a snapshot, record a
*new* snapshot tagged `corrected_from=<old_id>`; never mutate the
original.

---

## Running the migrations

```bash
# Fresh DB
alembic upgrade head      # applies 0001_baseline → 0002_pricing → 0003_seed

# Existing dev DB that pre-dates Stage 0
alembic stamp 0001_baseline   # tell Alembic Stage 0 schema is in place
alembic upgrade head           # apply Stage 1

# Re-seed only (eg. after dropping seed rows)
alembic downgrade 0002_stage1_pricing
alembic upgrade head
# 0003 deletes only `WHERE source LIKE 'seed:%'`, so admin edits survive.
```

---

## Migration of remaining consumers (Stage 3 preview)

These services still import the legacy modules and will migrate in
Stage 3 using the same pattern:

| Service | Reads from | Stage 3 target |
|---|---|---|
| `cost_breakdown_service.py` | `costing` | `CostFactorRepository` + `LaborRateRepository` |
| `manufacturing_spec_service.py` | `costing`, `materials`, `regional_materials` | All four pricing repos |
| `material_spec_service.py` | `costing`, `materials`, `regional_materials` | `MaterialPriceRepository` |
| `pricing_service.py` | `costing` | `CostFactorRepository` |
| `sensitivity_service.py` | `costing` | `CostFactorRepository` |
| `mep_spec_service.py` | `regional_materials` | `CityPriceIndexRepository` |

Until Stage 3 lands, these services see **stale data** if an admin
updates a price in DB. Stage 1's deprecation notices in the legacy
files warn about this.

---

## Quick gotcha checklist for future-you

- [ ] Editing `costing.py` / `regional_materials.py` / cost fields of
      `materials.py`? **Stop.** Use `/admin/pricing/...` instead.
- [ ] Adding a new cost constant? Add it to:
      1. `app.services.pricing.seed` (`cost_factor_rows()`)
      2. The seed migration if a fresh insert is needed
      3. `build_pricing_knowledge` (so the cost engine sees it)
      4. `app.services.cost_engine_service` system prompt + JSON schema
- [ ] Adding a new business table? Compose **all** Stage-0 mixins and
      add a partial unique index on the logical key. See
      `docs/foundations.md`.
- [ ] Reproducing an old estimate? Pass `?snapshot_id=...` to the
      cost-engine endpoint; never re-fetch from current DB.
