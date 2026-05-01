# KATHA-AI — Solo-Dev Operations Runbook

> The doc you read at 2 AM when you've forgotten how to deploy your
> own platform. Optimise for "find the answer fast," not "explain
> the theory."

## TL;DR

| Need to… | Section |
|---|---|
| Boot the API locally | [Local dev](#local-dev) |
| Deploy to prod | [Deploy](#deploy) |
| Run a migration | [Migrations](#migrations) |
| See live logs | [Observability](#observability) |
| Backup the DB | [Backups](#backups) |
| Restore from backup | [Restore](#restore) |
| Investigate a 500 | [Debug a 500](#debug-a-500) |
| Investigate a slow request | [Performance](#performance) |
| Rotate a secret | [Secrets](#secrets) |
| Add an admin user | [Admin users](#admin-users) |

## Local dev

```bash
# 1. Postgres + Redis
docker compose up -d postgres redis

# 2. Python deps
cd backend
pip install -r requirements.txt

# 3. Migrate to head
alembic upgrade head

# 4. Boot the API
uvicorn app.main:app --reload --port 8000

# 5. Boot Celery (separate terminal — required for any async indexing
#                + Stage 8 nightly extraction + future scheduled jobs)
celery -A app.workers.celery_app worker --loglevel=info \
  --queues=generation,estimation,rendering,ingestion
celery -A app.workers.celery_app beat --loglevel=info
```

### Required env

Source from `backend/.env` (gitignored). Minimum to boot:

```
DATABASE_URL=postgresql+asyncpg://katha:katha@localhost:5432/katha
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<any-non-default-string>
ANTHROPIC_API_KEY=<required for agent features>
OPENAI_API_KEY=<required for embeddings + Stage 4D specs>
```

Optional, feature-gated:

```
GEMINI_API_KEY=                     # Stage 7 image generation
S3_ENDPOINT=                        # S3-compat storage (else local disk)
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=
OTEL_EXPORTER_OTLP_ENDPOINT=        # Honeycomb/Grafana/Sentry — Stage 13
OTEL_EXPORTER_OTLP_HEADERS=         # API key etc.
SLACK_WEBHOOK_URL=                  # Stage 12 anomaly alerts (when enabled)
```

`Settings.assert_production_safe()` runs at boot and refuses to
launch in non-dev environments with default secrets — `JWT_SECRET=
change-me-in-production` will hard-fail. That's intentional; fix
your env, don't suppress the check.

## Deploy

The repo has no opinionated deployment target — any container host
that can run a Python ASGI app + Postgres + Redis works. Reference
sequence:

1. **Tag** — `git tag v0.x.0 && git push --tags`. Stamp this tag
   into `OTEL_RESOURCE_ATTRIBUTES=service.version=v0.x.0` in your
   deployment env so spans carry the version.
2. **Migrate first, deploy second** — the API's `lifespan` hook
   does NOT auto-run migrations (Stage 0 decision). The deploy
   pipeline must run `alembic upgrade head` against the target DB
   before swapping the container.
3. **Health check** — load balancers should hit `GET /health`.
   Returns `{"status": "ok", "version": "0.2.0"}` once the app is
   ready to serve.
4. **Drain on shutdown** — uvicorn handles SIGTERM correctly; give
   workers ≥30s grace.
5. **Celery workers** — separate process. The API can serve reads
   without the worker; writes that defer to Celery (memory
   indexing, profile extraction) silently degrade if the broker
   is unhealthy. Monitor the broker queue depth.

## Migrations

```bash
# Status
alembic current
alembic history --verbose | head -30

# Apply
alembic upgrade head

# Generate (after editing models/orm.py)
alembic revision --autogenerate -m "what changed"

# Roll back one
alembic downgrade -1
```

Migrations are numbered sequentially (`0001_…` to `0022_…` as of
Stage 13). When merging branches:

- Conflicting numbers → renumber the later one to be a child of
  the earlier (`down_revision` chain).
- Never edit a migration that has shipped. Add a follow-up.

## Observability

### Logs

Stage 0 ships JSON structured logs in non-debug mode. Every line
carries `request_id`. Find a slow request by:

```bash
# In your log aggregator:
request_id="req-abc123"

# Or with raw container logs:
docker logs katha-api 2>&1 | jq 'select(.request_id == "req-abc123")'
```

### Tracing (OTEL)

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable. Without it, spans go
nowhere (intentional — better than spamming localhost:4318).

```
# Honeycomb
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io:443
OTEL_EXPORTER_OTLP_HEADERS=x-honeycomb-team=YOUR_API_KEY
OTEL_SERVICE_NAME=katha-api

# Grafana Cloud
OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-0.grafana.net/otlp
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(instance:token)>
```

`app/observability/otel.py:install()` returns `False` and logs
when the endpoint isn't set — boot logs tell you exactly what
happened.

### Audit log

Every write tool + admin route writes one row to `audit_events`
with `target_type` + `target_id` + `before` / `after` JSON +
`request_id`. Common queries:

```sql
-- Every haptic export for project X
SELECT * FROM audit_events
WHERE target_type = 'haptic_export'
  AND target_id = 'PROJ_X'
ORDER BY created_at DESC
LIMIT 50;

-- All actions in one request
SELECT * FROM audit_events
WHERE request_id = 'req-abc'
ORDER BY created_at;
```

## Backups

```bash
cd backend
./scripts/backup.sh
# → ./backups/db_20260501T103045Z.dump.gz
#   ./backups/uploads_20260501T103045Z.tar.gz
#   ./backups/manifest_20260501T103045Z.json
```

The script is idempotent — schedule it via cron / systemd / Celery
beat. When `S3_BUCKET` + `S3_ENDPOINT` are set, it also pushes to
S3 under `backups/<timestamp>/`.

Recommended cadence:

| Layer | Frequency | Retention |
|---|---|---|
| Postgres | hourly | 14 days hot, 90 days cold |
| Uploads tree | daily | 30 days hot |
| Manifest only | every backup | forever |

Pruning is the operator's job. A simple cron:

```bash
find /var/backups/katha -mtime +30 -type f -delete
```

## Restore

Restoration is **destructive**. The script refuses to run unless
you opt in:

```bash
RESTORE_CONFIRM=yes ./scripts/restore.sh 20260501T103045Z
```

Sequence:

1. Stop API + Celery workers — concurrent writes during restore
   produce inconsistent state.
2. Run `restore.sh` with the desired timestamp.
3. Verify: `alembic current` should show the same revision as the
   manifest's `alembic_version`.
4. Boot the app, then Celery.
5. Smoke-test: `GET /health`, `GET /api/v1/projects` (requires
   auth), then a known-good agent chat round-trip.

If the restore fails part-way, the database is in a half-restored
state. Restoring again over it is safe — the script drops the
public schema on each run.

## Debug a 500

Every error response now carries:

```json
{
  "error": "internal_error",
  "message": "...",
  "request_id": "req-abc123"
}
```

Workflow:

1. Grab `request_id` from the failed response.
2. Search logs for `request_id="req-abc123"`.
3. Pre-error timeline → app trace → audit row(s).
4. If the failure is in a tool call, check `audit_events` for
   `target_type=<the tool>` near the same timestamp — the audit
   row has the input + output keys + elapsed_ms.

For agent failures specifically, the agent loop persists tool
calls + responses in `chat_messages` (Stage 5). Surface the chain
with `recall_design_decisions` or read the table directly.

## Performance

```sql
-- Slow query starter pack (PostgreSQL).
SELECT pid, now() - query_start AS duration, state, query
FROM pg_stat_activity
WHERE state != 'idle' AND now() - query_start > interval '1 second'
ORDER BY duration DESC;

-- Top tables by sequential scan ratio (missing index?).
SELECT schemaname, relname,
       seq_scan, seq_tup_read,
       idx_scan, idx_tup_fetch,
       seq_tup_read::float / NULLIF(idx_tup_fetch, 0) AS seq_ratio
FROM pg_stat_user_tables
ORDER BY seq_ratio DESC NULLS LAST
LIMIT 20;
```

Application side:

- Every tool call's `elapsed_ms` is in `audit_events.after`. Find
  outliers per tool with one query.
- The agent loop logs `tool.<name> ok elapsed_ms=...` for every
  call.
- Stage 13 added defensive composite indexes on the heaviest
  query paths (`audit_events`, `chat_messages`, `project_memory_chunks`,
  `estimate_snapshots`, `generated_assets`). Re-running
  `alembic upgrade head` is safe — index creation is `IF NOT EXISTS`.

When you have real load: see `docs/performance-playbook.md`.

## Secrets

Stored in `.env` (gitignored). Rotation procedure:

1. Generate new value (per the secret type — JWT secret = 32+
   chars random; API keys = via the issuer).
2. Update `.env` on every host running the API.
3. **For JWT secret rotation specifically:** existing tokens
   become invalid. If you can't drop all sessions, run with both
   old + new for a rollover window (current implementation only
   reads one — extend `auth_service.decode_access_token` to try
   both during rollover).
4. Restart the API + Celery workers.

Never commit secrets. Stage 0's `assert_production_safe` blocks
the boot when `JWT_SECRET=change-me-in-production` is detected
in non-dev environments.

## Admin users

Admin endpoints (`/api/v1/admin/...`) currently allow any
authenticated user — RBAC enforcement is on the Stage 13B/UI
phase roadmap (see `docs/security-checklist.md`). For now:

- Local dev: ignore — the dev user shim allows anonymous access.
- Pre-UI prod: gate the admin paths at the load balancer / proxy
  level until RBAC ships.

## When you're stuck

| Symptom | Where to look |
|---|---|
| `/health` returns 500 | Boot logs — likely `Settings.assert_production_safe()` failure |
| API returns 401 on every call | JWT secret rotated mid-flight; old tokens invalid |
| Agent calls fail with `internal_error` | Anthropic / OpenAI API key, rate limit, or quota |
| Migrations won't run | Check `alembic current` vs `alembic history` for chain breaks |
| Worker queue depth growing | Celery worker dead or slow; restart and check broker |
| OTEL not appearing in backend | Endpoint env var unset, or vendor headers wrong; check boot log line `otel.installed` |
| Rate limit headers missing | Redis unreachable — middleware soft-fails; check Redis health |

When the docs don't have it: `git log --all --oneline --grep "<topic>"`
usually surfaces the commit that introduced whatever you're
debugging. Each commit message documents the *why*.
