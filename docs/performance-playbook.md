# Performance Playbook

> Stage 13 ships index hygiene + a profiling playbook. The actual
> P95 numbers come from running load against your deployment —
> this doc tells you how to get there.

## Index hygiene (shipped Stage 13)

Migration `0022_stage13_indexes` adds composite indexes covering
the heaviest-traffic query paths. All `CREATE INDEX IF NOT EXISTS`
— safe to re-run, additive. Indexes added:

| Index | Path it covers |
|---|---|
| `ix_audit_events_request_recent` | "Show me everything that happened during request X" — Stage 11 challenge follow-up |
| `ix_chat_messages_session_recent` | Chat history pagination — hottest read |
| `ix_project_memory_chunks_project_source` | Stage 5C re-index (DELETE by `(project_id, source_type, source_id)`) |
| `ix_estimate_snapshots_graph_recent` | Newest estimate per design version |
| `ix_generated_assets_graph_recent` | Drawings/diagrams listing |

Existing indexes from prior stages cover the project / owner /
session / haptic catalog query paths; Stage 13 doesn't change any
of those.

## Load test starter

No load harness ships with the repo (intentional — depends on your
infra). Recommended starting point:

```bash
# Install
pip install locust

# locustfile.py — minimal example
from locust import HttpUser, task, between

class KathaUser(HttpUser):
    wait_time = between(1, 3)
    host = "http://localhost:8000"

    def on_start(self):
        # Replace with real auth flow once you have one in your env
        self.client.headers.update({"Authorization": "Bearer dev-token"})

    @task(3)
    def list_projects(self):
        self.client.get("/api/v1/projects")

    @task(1)
    def chat(self):
        self.client.post("/api/v1/agent/chat", json={
            "message": "estimate cost for a small kitchen",
        })

# Run
locust -f locustfile.py --headless -u 50 -r 5 -t 5m
```

50 concurrent users for 5 minutes is enough to surface obvious
hotspots without overwhelming a dev DB.

## Where to look first

Order of investigation when latency spikes:

### 1. Per-tool elapsed_ms

Every agent tool call writes `elapsed_ms` into
`audit_events.after`. Find the offenders:

```sql
SELECT
    after->>'tool' AS tool,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY (after->>'elapsed_ms')::float) AS p50,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY (after->>'elapsed_ms')::float) AS p95,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY (after->>'elapsed_ms')::float) AS p99,
    COUNT(*) AS calls
FROM audit_events
WHERE created_at > now() - interval '1 hour'
  AND after ? 'tool'
GROUP BY 1
ORDER BY p95 DESC
LIMIT 20;
```

Anything with `p95 > 5000ms` is suspicious unless it's a known LLM
tool (specs / drawings / cost engine — these can legitimately take
several seconds).

### 2. Postgres slow queries

```sql
-- Currently slow
SELECT pid, now() - query_start AS duration, state, query
FROM pg_stat_activity
WHERE state != 'idle' AND now() - query_start > interval '500 ms'
ORDER BY duration DESC;

-- Sequential-scan offenders (missing index?)
SELECT schemaname, relname,
       seq_scan, seq_tup_read,
       idx_scan,
       seq_tup_read::float / GREATEST(idx_tup_fetch, 1) AS seq_ratio,
       n_live_tup
FROM pg_stat_user_tables
WHERE n_live_tup > 1000
ORDER BY seq_ratio DESC
LIMIT 20;
```

A `seq_ratio > 10` on a table with > 10k rows usually means a
missing index. Add one in a new migration; do **not** edit a
shipped migration.

### 3. Embedding / RAG queries

Stage 5B/6 use pgvector. Watch for:

- IVFFlat index missing → seq scan over the embedding column
- Wrong `lists=` parameter → too coarse or too fine, mediocre recall
- Embeddings table > 1M rows without partitioning

Check the pgvector index plan:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, 1 - (embedding <=> '[...]'::vector) AS sim
FROM project_memory_chunks
WHERE project_id = 'PROJ_123'
ORDER BY embedding <=> '[...]'::vector
LIMIT 5;
```

Should show an `Index Scan using ix_project_memory_chunks_embedding`,
not `Seq Scan`.

### 4. Async indexing backlog

Stage 5D allows async indexing via Celery. If `async_indexing_enabled`
is true and the worker is slow, search results lag the actual
design changes. Monitor:

```sql
SELECT source_type, COUNT(*) AS count
FROM project_memory_chunks
GROUP BY source_type;
```

Compare the `design_version` count vs `design_graph_versions` row
count — gap = backlog.

## Caching the agent loop

The Stage 5+ agent loop persists every chat message and tool call.
That's a lot of small writes. If write latency becomes a problem:

1. Confirm `task_acks_late=True` on Celery (already set).
2. Confirm Postgres `synchronous_commit=off` on the audit DB. Audit
   loss in a crash window is acceptable; latency tax isn't.
3. Consider batching `audit_events.record()` calls per request via
   a write-behind queue.

Don't do any of these until profiling shows a real problem. Stage
13 ships them as untaken tradeoffs.

## What we deliberately do NOT cache

- LLM responses (every call is part of an audit chain)
- RAG retrievals (results depend on freshness of the corpus)
- Cost engine outputs (validators must re-walk the math)

Caching these would break either the audit trail or the
deterministic re-walks the validators rely on. The performance
cost is intentional.

## When to add an index

Heuristics:

- A column appears in `WHERE` of any tool's "list / count / search"
  query and the table has > 10k rows.
- A pair of columns appears together in `ORDER BY` on a hot path
  (composite index).
- `EXPLAIN ANALYZE` shows a `Seq Scan` over > 10% of the table.

Don't add indexes pre-emptively — every index is a write tax. Wait
until the profiler tells you which one is missing.
