#!/usr/bin/env bash
# Stage 13 — KATHA-AI backup script.
#
# Single command that produces three artefacts in $BACKUP_DIR:
#
#   1. db_<ts>.dump.gz          — pg_dump custom format, gzipped
#   2. uploads_<ts>.tar.gz       — local-storage tree (Stage 7)
#   3. manifest_<ts>.json        — alembic version + git sha + sizes
#
# Schedule via cron / systemd / Celery beat. Restoration is the
# inverse — see docs/backup-restore.md.
#
# Required env (from ../.env or the shell):
#   DATABASE_URL      postgres://... (asyncpg url accepted; rewritten)
# Optional:
#   BACKUP_DIR        defaults to ./backups
#   STORAGE_LOCAL_ROOT  uploads dir (default ./uploads)
#   S3_*              when set, the script also uploads the trio to S3
#                     (see s3_sync.py for the actual upload).
#
# The script is idempotent: a second run produces a fresh timestamped
# bundle. Old bundles aren't deleted — pruning is the operator's
# call (cron a "find -mtime +30 -delete" on $BACKUP_DIR).

set -euo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=${BACKUP_DIR:-./backups}
UPLOADS_DIR=${STORAGE_LOCAL_ROOT:-./uploads}
mkdir -p "$BACKUP_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[backup] DATABASE_URL not set" >&2
  exit 1
fi

# pg_dump wants postgresql://; strip asyncpg dialect if present.
PG_URL="${DATABASE_URL//postgresql+asyncpg:/postgresql:}"

echo "[backup] $TS — dumping database"
pg_dump --no-owner --no-privileges -Fc "$PG_URL" \
  | gzip -9 > "$BACKUP_DIR/db_${TS}.dump.gz"

if [[ -d "$UPLOADS_DIR" ]]; then
  echo "[backup] $TS — archiving uploads tree ($UPLOADS_DIR)"
  tar -czf "$BACKUP_DIR/uploads_${TS}.tar.gz" -C "$(dirname "$UPLOADS_DIR")" \
    "$(basename "$UPLOADS_DIR")"
else
  echo "[backup] $TS — no uploads dir at $UPLOADS_DIR (S3 backend?)"
fi

# Manifest.
ALEMBIC_VERSION=$(
  cd "$(dirname "$0")/.."
  if command -v alembic >/dev/null 2>&1; then
    alembic current 2>/dev/null | tr '\n' ' ' || echo "unknown"
  else
    echo "alembic_not_installed"
  fi
)
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
DB_SIZE=$(stat -f%z "$BACKUP_DIR/db_${TS}.dump.gz" 2>/dev/null \
          || stat -c%s "$BACKUP_DIR/db_${TS}.dump.gz" 2>/dev/null \
          || echo "0")

cat > "$BACKUP_DIR/manifest_${TS}.json" <<EOF
{
  "timestamp": "${TS}",
  "alembic_version": "${ALEMBIC_VERSION}",
  "git_sha": "${GIT_SHA}",
  "db_artefact": "db_${TS}.dump.gz",
  "db_bytes": ${DB_SIZE},
  "uploads_artefact": "uploads_${TS}.tar.gz"
}
EOF

echo "[backup] $TS — wrote manifest"
echo "[backup] $TS — done. Artefacts in $BACKUP_DIR/"
ls -lh "$BACKUP_DIR/"*"_${TS}"*

# Optional S3 sync. Soft-fail — operator can re-run the python helper.
if [[ -n "${S3_BUCKET:-}" ]] && [[ -n "${S3_ENDPOINT:-}" ]]; then
  echo "[backup] $TS — syncing to S3 (bucket=${S3_BUCKET})"
  python3 -m app.services.backup.s3_sync \
    "$BACKUP_DIR/db_${TS}.dump.gz" \
    "$BACKUP_DIR/uploads_${TS}.tar.gz" \
    "$BACKUP_DIR/manifest_${TS}.json" \
    || echo "[backup] $TS — S3 sync failed (artefacts still on disk)"
fi
