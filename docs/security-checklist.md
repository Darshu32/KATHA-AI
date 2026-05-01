# Security Checklist

> Operator-facing audit + procedure. Walk this before every
> production deploy, before every dependency bump, and once a
> quarter regardless.

## Authentication

- [ ] `JWT_SECRET` is set to a production-grade value (≥ 32 bytes
      random) on every host.
- [ ] `Settings.assert_production_safe()` runs at boot and refuses
      `JWT_SECRET=change-me-in-production`. Confirm by tailing the
      boot logs of a fresh deploy.
- [ ] JWT expiry is configured (default in `auth_service.py` is
      24h). Adjust per environment.
- [ ] Token refresh / rollover documented for the operator
      (currently single-secret; rotate per `docs/operations.md`).

## Authorization

- [ ] Owner-guard on every project-scoped read/write. Stage 8/11
      pattern: cross-owner returns 404 with the same shape as
      "not found" — no existence leakage.
- [ ] Admin endpoints (`/api/v1/admin/...`) gated. **Stage 13
      ship status: PARTIAL** — admin routes don't yet check a
      role flag. Mitigate at the load balancer / proxy until RBAC
      lands. (See `docs/adr/0006-stub-provider-pattern.md` for
      why we ship interfaces before enforcement when there's no
      role model yet.)

## Secrets

- [ ] No secret committed to git. `git log --all --diff-filter=A
      --pretty=format: --name-only | sort -u | grep -i 'env\|key\|secret'`
      → empty.
- [ ] `.gitignore` covers `.env`, `*.pem`, `*.key`, `id_rsa*`.
- [ ] `Settings.redacted_dict()` used wherever settings are
      logged. Don't log the raw `Settings` object.
- [ ] All secrets sourced from env vars, never code constants.

## Inputs

- [ ] Pydantic v2 validates every API boundary (auto-enforced by
      FastAPI route signatures).
- [ ] Tool inputs validated by the `@tool` framework (Stage 2+).
- [ ] String fields have `max_length` to bound LLM-generated /
      attacker payloads.
- [ ] `JSONB` fields don't get directly indexed without an explicit
      decision — large JSONB rows would balloon write amplification.

## Output

- [ ] Every response goes through the canonical error envelope
      (Stage 13 — `install_error_handlers`). No raw stack traces
      to clients.
- [ ] Audit logs strip raw secrets — `app/db/audit.py` writes
      keyed `before` / `after` JSON. Don't pass secrets through.
- [ ] LLM outputs not echoed verbatim into logs at INFO level —
      they may contain user PII / brief data the user didn't
      mean to publicise.

## Rate limiting

- [ ] Stage 13 sliding-window middleware installed
      (`app/middleware/rate_limit.py`). Confirm Redis is reachable
      — when down, the middleware soft-fails and lets traffic
      through. That's a feature for availability, but it means
      you should monitor Redis health.
- [ ] Per-tool LLM tier (60/min/user default) appropriate for
      your traffic budget. Lower for free tier; raise for paid.

## Dependencies

- [ ] `pip-audit` (or `safety check`, or `osv-scanner`) clean. Run
      it in CI on every push.
- [ ] Pinned versions in `requirements.txt`. Floating deps in
      production are a CVE waiting to happen.
- [ ] No `*` or unpinned transitive deps for security-critical
      libs (cryptography, pyjwt, sqlalchemy).

## Database

- [ ] Postgres runs as a non-superuser app account (not `postgres`).
- [ ] Connection uses TLS in production (`sslmode=require` in the
      DSN).
- [ ] `pg_hba.conf` doesn't allow `trust` for the app account.
- [ ] Backups encrypted at rest (S3 SSE-S3 or SSE-KMS). The Stage
      13 backup script doesn't enforce this — your S3 bucket
      policy must.

## Storage (S3-compat)

- [ ] Bucket NOT public. Object ACL = bucket-owner-full-control.
- [ ] CORS policy restricted to your frontend origin.
- [ ] Pre-signed URLs (Stage 7) have short expiry (≤ 15 min default).
- [ ] Bucket access logging on (provider-dependent).

## LLM providers

- [ ] Anthropic + OpenAI keys scoped to per-environment accounts
      (separate dev / staging / prod). One leaked key shouldn't
      impact prod.
- [ ] Per-environment usage quota set at the provider dashboard
      (Anthropic console / OpenAI usage limits). Belt + suspenders
      against runaway loops.
- [ ] Tool calls have `timeout_seconds` set (every `@tool` does;
      framework default 30s).

## Headers

- [ ] CORS origins (`Settings.cors_origins`) restricted in prod —
      default is `["http://localhost:3000"]`, harmless in dev,
      catastrophic in prod if uneditted.
- [ ] HSTS + secure cookies handled at the load balancer.

## Logging / observability

- [ ] Logs structured JSON in prod (Stage 0 default with
      `debug=False`).
- [ ] PII-scrubbing pass on log shipping (e.g. email addresses
      shouldn't ride to a third-party log SaaS unless documented).
- [ ] OTEL endpoint uses TLS. The OTLP exporter ships HTTPS by
      default; confirm in the boot log line `otel.installed
      endpoint=https://...`.

## Security updates

| Cadence | Action |
|---|---|
| Weekly | `pip-audit` in CI |
| Monthly | Dependency bump PR (Dependabot or manual) |
| Quarterly | Walk this checklist end-to-end |
| Per CVE | Same-day patch for any CVE on `cryptography`, `sqlalchemy`, `fastapi`, `uvicorn`, `pyjwt`, the LLM SDKs |

## Open items (Stage 13 ship debt)

- **Admin RBAC** — admin routes assume any authenticated user is
  admin. Pre-UI mitigation: gate at the proxy. Roadmap: roles
  table + `require_role("admin")` dependency.
- **Per-tenant key scoping** — currently single-tenant model
  (every user's projects share the LLM key budget). Multi-tenant
  scoping is post-Phase-1.
- **Audit log encryption-at-rest** — relies on Postgres-level
  encryption. Field-level encryption for sensitive `before`/
  `after` payloads is on the long-tail roadmap.
