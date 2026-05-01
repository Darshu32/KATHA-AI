# Backup & Restore

> Two scripts. One Python helper. Three artefact types per backup.
> Disaster recovery in well under an hour for a healthy DB and S3
> trio.

## What gets backed up

| Layer | Artefact | Source |
|---|---|---|
| Postgres (entire DB incl. RAG, decisions, haptic catalog, audit log) | `db_<ts>.dump.gz` | `pg_dump -Fc` then gzip |
| Local uploads tree (when `STORAGE_BACKEND=local`) | `uploads_<ts>.tar.gz` | `tar -czf` over `STORAGE_LOCAL_ROOT` |
| Manifest | `manifest_<ts>.json` | Computed by the script |

When `STORAGE_BACKEND=s3` the uploads tree archive is skipped —
S3 itself is the source of truth, and the bucket should have its
own versioning + lifecycle policy.

## What does NOT get backed up

- Redis (broker + cache only — no canonical state).
- Celery task results (`celery_result_backend` is Redis; results
  are ephemeral by design).
- LLM provider state (no canonical state on KATHA's side).

## Run a backup

```bash
cd backend
./scripts/backup.sh
```

Default behaviour:

- Reads `DATABASE_URL` and `STORAGE_LOCAL_ROOT` from `.env`.
- Writes artefacts to `./backups/` (override with `BACKUP_DIR`).
- If `S3_BUCKET` + `S3_ENDPOINT` set, also pushes to S3 under
  `backups/<timestamp>/`.

The script is idempotent — every run produces a new timestamped
trio. Old artefacts aren't removed automatically.

### Schedule

Recommended cadence:

| Cadence | Where | Why |
|---|---|---|
| Hourly | cron / systemd timer | Postgres only — not the uploads tree |
| Daily | cron | Full bundle (DB + uploads) |
| Pre-deploy | Manual | Take a known-good baseline before applying migrations |

Hourly DB-only example (`crontab -e`):

```
0 * * * * cd /opt/katha/backend && BACKUP_DIR=/var/backups/katha-hourly ./scripts/backup.sh >>/var/log/katha/backup.log 2>&1
```

Don't run hourly + daily into the same `BACKUP_DIR` — `find -mtime
+30 -delete` will reap your "intentional" daily snapshots
alongside the hourly ones. Separate dirs.

## Restore

**Destructive operation. Drops + recreates the public schema.**

```bash
cd backend
RESTORE_CONFIRM=yes ./scripts/restore.sh 20260501T103045Z
```

Procedure:

1. Stop API + Celery workers — concurrent writes during restore
   produce inconsistent state.
2. Run the restore script. It refuses without `RESTORE_CONFIRM=yes`.
3. Verify: `alembic current` should show the same revision as
   `manifest.alembic_version`.
4. If they differ: run `alembic upgrade head` to bring the schema
   forward (forward migrations from the snapshot's revision must
   exist in the current code tree).
5. Boot API, then Celery workers.
6. Smoke-test:
   - `GET /health` → 200
   - Auth round-trip (issue token + use it)
   - Read a known project: `GET /api/v1/projects`
   - Trigger one tool through `/api/v1/agent/chat`

If the restore fails part-way, the database is in a half-restored
state. Re-running the script over it is safe — the script drops
the public schema on each run.

## Restore from S3-only backup

When local artefacts have been pruned but S3 still has the bundle:

```bash
mkdir -p /tmp/restore
aws s3 cp --recursive s3://katha-prod/backups/20260501T103045Z/ /tmp/restore/
BACKUP_DIR=/tmp/restore RESTORE_CONFIRM=yes ./scripts/restore.sh 20260501T103045Z
```

(Replace `aws s3` with `mc cp` etc. for non-AWS providers.)

## Test restores

Untested backups don't exist. Schedule a quarterly restore drill:

1. Provision a throwaway Postgres + storage env.
2. Run `restore.sh` against the throwaway.
3. Boot the app pointing at the throwaway DB.
4. Run a smoke-test pass (or `pytest tests/integration -k "smoke"`).
5. Tear down the throwaway.

Document the elapsed time. Aim for < 30 min cold-restore-to-
serving. If it takes longer, the bottleneck is usually one of:
network I/O for the DB dump, pg_restore parallelism (`-j N`), or
uploads-tree size.

## Encryption at rest

The Stage 13 scripts produce gzipped artefacts but **don't
encrypt** them. Two options:

- **At the storage layer** (recommended) — your S3 bucket has
  SSE-S3 or SSE-KMS enabled. Local backup directories live on
  encrypted volumes (LUKS / FileVault / BitLocker).
- **At the artefact layer** — wrap with `gpg --symmetric` or
  `age`. Document the key in a separate location (1Password vault,
  not the same machine).

Pick one and write it down here in your fork.

## Manifest format

```jsonc
{
  "timestamp": "20260501T103045Z",
  "alembic_version": "0022_stage13_indexes",
  "git_sha": "f7805c1",
  "db_artefact": "db_20260501T103045Z.dump.gz",
  "db_bytes": 245760000,
  "uploads_artefact": "uploads_20260501T103045Z.tar.gz"
}
```

The manifest is what the restore script reads to confirm what
schema generation matches the dump. Keep it next to the artefacts;
S3 sync uploads it alongside.

## Known limitations

- The script doesn't snapshot `pg_largeobject` separately. KATHA
  doesn't use large objects — verify before assuming this is
  sufficient for your fork.
- `pg_dump -Fc` is a logical dump. For very large databases (>
  100 GB) the dump duration grows linearly; consider physical
  backups via `pg_basebackup` or `Barman` at that scale.
- The Stage 13 scripts are bash. Windows operators should run
  them under WSL or rewrite to PowerShell — the logic is short.
