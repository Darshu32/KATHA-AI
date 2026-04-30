# KATHA-AI — Foundations (Stage 0)

> **Audience:** future-you, six months from now, wondering "why is the data
> layer shaped like this?"
>
> This document is the reference for everything Stage 0 introduced. Read
> it before adding new tables, services, or tools.

---

## What Stage 0 set up

| Concern | Where | Why |
|---|---|---|
| Schema migrations | `backend/alembic/versions/0001_baseline.py` | Replaces `Base.metadata.create_all`; all schema changes go through Alembic from now on. |
| Schema conventions | `backend/app/db/conventions.py` | Mixins every business-data model composes from. |
| Audit log | `backend/app/db/audit.py` (`audit_events` table) | Append-only record of every meaningful change. |
| Repository pattern | `backend/app/db/repository.py` | One place per model for queries; soft-delete + versioning baked in. |
| Caching | `backend/app/db/cache.py` | Redis decorator with per-namespace invalidation. |
| Secrets | `backend/app/config.py` | `assert_production_safe()` refuses to boot with default secrets in non-dev environments. |
| Request IDs | `backend/app/observability/request_id.py` | Every request carries an ID through logs + audit events. |
| Logging | `backend/app/observability/logging.py` | JSON in prod, pretty in dev; auto-attaches `request_id`. |
| Tests | `backend/tests/` | Unit-only by default; integration tests gated by `KATHA_INTEGRATION_TESTS=1`. |
| Lint/format/types | `backend/pyproject.toml`, `.pre-commit-config.yaml` | Ruff + mypy + pre-commit. |
| CI | `.github/workflows/backend.yml` | Lint/format/typecheck/unit on every push. |

---

## The conventions every business-data model must follow

Stage 1+ introduces tables for **prices, themes, materials, codes, vendor
catalogs, etc.** Every such table composes the following mixins. Skipping
one breaks downstream guarantees.

### Required for *all* business data

```python
from app.database import Base
from app.db import (
    UUIDMixin,           # 32-char hex UUID primary key
    TimestampMixin,      # created_at / updated_at
    SoftDeleteMixin,     # deleted_at — never DELETE rows
    SourceMixin,         # source + source_ref ("seed", "admin", "scraper:mcx")
    ActorMixin,          # created_by user (nullable for system actors)
)

class MaterialPrice(
    Base,
    UUIDMixin,
    TimestampMixin,
    SoftDeleteMixin,
    SourceMixin,
    ActorMixin,
):
    __tablename__ = "material_prices"
    # … your columns …
```

### Required when the data has **history** (almost always)

```python
from app.db import VersionedMixin, EffectiveDatesMixin

class MaterialPrice(..., VersionedMixin, EffectiveDatesMixin):
    ...
```

These two together guarantee:

- Old estimates **reproduce identically** with the prices that were active
  when they were generated (Stage 1 snapshots `effective_from <= when`).
- Updates create new rows. Nothing is overwritten.
- Rollback is an INSERT, not a destructive operation.

### Migration must enforce single-current-version invariant

For any versioned table, add a partial unique index in the migration::

```python
op.create_index(
    "uq_material_prices_logical_current",
    "material_prices",
    ["material_id", "region"],          # the LOGICAL key
    unique=True,
    postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
)
```

This prevents two rows from claiming "I'm the current version" for the
same logical record. The application layer enforces the same invariant,
but the DB index is the safety net.

---

## How writes work (cookbook)

### Creating the first version of a logical record

```python
repo = MaterialPriceRepository(session)
price = await repo.create(
    {
        "material_id": walnut.id,
        "region": "mumbai",
        "price_per_kg": 720.0,
    },
    actor_id=current_user.id,
    reason="Initial seed from BRD",
    request_id=get_request_id(),
)
```

This:
1. Inserts a row with `version=1, is_current=True`.
2. Records an `AuditEvent(action="create", before={}, after={...})`.

### Updating (= creating a new version)

```python
old = await repo.get_active_for(material=walnut, region="mumbai", when=now())
new = await repo.create_versioned(
    old,
    {"price_per_kg": 745.0},
    actor_id=current_user.id,
    reason="Monthly rate sheet — May 2026",
    request_id=get_request_id(),
)
```

This:
1. Sets `old.is_current = False` and `old.effective_to = now`.
2. Inserts a new row with `version = old.version + 1, is_current = True`,
   `previous_version_id = old.id`, `effective_from = now`,
   `effective_to = NULL`.
3. Records an `AuditEvent(action="update", before=..., after=...)`.

**Never UPDATE a versioned row in place.** That breaks Stage 1's promise
that old estimates reproduce.

### Soft-delete

```python
await repo.soft_delete(price, actor_id=user.id, reason="Vendor delisted")
```

Sets `deleted_at` and writes an audit event. Future queries via the
repository skip this row.

---

## Reads: snapshots, not "now"

Estimates and similar artifacts **must** capture the data they used at
the moment they were created. Pattern:

```python
estimate.created_at = datetime.now(timezone.utc)
price = await repo.get_active_for(
    material=walnut, region="mumbai", when=estimate.created_at,
)
```

Re-fetching the estimate later uses the SAME `when` and gets the SAME
price, even after the live price has changed N times.

---

## Caching

Wrap pure-read repository methods with `@async_cached(namespace=..., ttl=...)`.
Invalidate on writes:

```python
from app.db import async_cached, invalidate

class MaterialPriceRepository(BaseRepository[MaterialPrice]):
    model = MaterialPrice

    @async_cached(namespace="material_price", ttl=300)
    async def get_active_for(self, *, material_id: str, region: str, when: datetime):
        ...

    async def update(self, ...):
        result = await self.create_versioned(...)
        await invalidate("material_price")
        return result
```

Cache failures never break the request — they fall back to live reads.

---

## Audit events

Every business write produces one row in `audit_events`. To add a custom
action (e.g. an agent tool call), call `AuditLog.record` directly:

```python
from app.db import AuditLog

await AuditLog.record(
    session,
    actor_kind="agent:cost_engine_tool",
    action="tool_call",
    target_type="estimate",
    target_id=estimate.id,
    after={"breakdown": ..., "confidence": 0.87},
    reason="Architect asked for sensitivity analysis",
    request_id=get_request_id(),
)
```

Read history of any entity:

```sql
SELECT * FROM audit_events
WHERE target_type = 'material_price' AND target_id = '...'
ORDER BY created_at DESC;
```

The `(target_type, target_id, created_at)` composite index makes this fast.

---

## Logging

```python
from app.observability import get_logger

log = get_logger(__name__)
log.info("price.updated", extra={"material_id": id_, "delta_pct": 4.2})
```

In dev: pretty single-line output with the request ID prefix.
In prod: JSON, ready for Loki / Datadog / whatever.

---

## Running locally

```bash
# Stack
docker compose up -d        # postgres + redis + migrate + api + worker

# Migrations only
docker compose run --rm migrate

# Tests
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/unit                                 # fast unit tests
KATHA_INTEGRATION_TESTS=1 pytest                  # full suite (needs DB+Redis)

# Lint / format / types
ruff check .
ruff format .
mypy app
pre-commit run --all-files
```

---

## What's intentionally NOT in Stage 0

- **OpenTelemetry tracing**: scaffolded in `app.observability` but not
  exported to a backend yet. Stage 13.
- **Rate limiting**: same — Stage 13.
- **OAuth / SSO**: only dev JWT for now. Future stage.
- **Database connection pooling tuning**: defaults are fine until load
  testing shows otherwise.

---

## When you forget what "active" means again

> "Active" = not soft-deleted **AND** (if versioned) `is_current=True`
> **AND** (if dated) `effective_from <= now < effective_to`.
>
> `BaseRepository._active_at(when)` encodes this. Always use it.

---

## Stage 0 → Stage 1 handover

Stage 1 (cost engine externalization) is the first real consumer of
everything in this document. When you start Stage 1:

1. **Read this doc**.
2. Define `MaterialPrice`, `LaborRate`, `CityPriceIndex`, `CostFactor`
   models — each composes the full mixin set above.
3. Add a Stage 1 migration (NOT in `0001_baseline.py`).
4. Subclass `BaseRepository[MaterialPrice]` etc.
5. Refactor `cost_engine_service.py` to use the repos.
6. Snapshot prices into estimates at creation time using `as_of`.
7. Delete `backend/app/knowledge/costing.py` and `regional_materials.py`
   only after Stage 1 regression tests pass.

The recipe is the same for Stage 3 (themes, MEP, clearances, …).
