#!/usr/bin/env bash
# Stage 13 — KATHA-AI restore script.
#
# Inverse of backup.sh. Takes one timestamp and restores both
# database + uploads tree from the artefacts in $BACKUP_DIR.
#
# Usage:
#   ./scripts/restore.sh 20260501T103045Z
#
# The script REFUSES to run unless $RESTORE_CONFIRM=yes — restores
# overwrite live data and a stray invocation can wipe production.
# The operator must opt in explicitly:
#
#   RESTORE_CONFIRM=yes ./scripts/restore.sh 20260501T103045Z
#
# Database restore drops + recreates the public schema. Make sure no
# app instances are running against the target DB while this runs.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <timestamp>" >&2
  exit 64
fi
TS=$1
BACKUP_DIR=${BACKUP_DIR:-./backups}
UPLOADS_DIR=${STORAGE_LOCAL_ROOT:-./uploads}

if [[ "${RESTORE_CONFIRM:-}" != "yes" ]]; then
  echo "[restore] refusing to run without RESTORE_CONFIRM=yes" >&2
  echo "[restore] this overwrites live data — set the env var to proceed" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "[restore] DATABASE_URL not set" >&2
  exit 1
fi

DB_FILE="$BACKUP_DIR/db_${TS}.dump.gz"
UPLOADS_FILE="$BACKUP_DIR/uploads_${TS}.tar.gz"
MANIFEST="$BACKUP_DIR/manifest_${TS}.json"

if [[ ! -f "$DB_FILE" ]]; then
  echo "[restore] db dump not found at $DB_FILE" >&2
  exit 1
fi

echo "[restore] $TS — manifest:"
[[ -f "$MANIFEST" ]] && cat "$MANIFEST"

PG_URL="${DATABASE_URL//postgresql+asyncpg:/postgresql:}"

echo "[restore] $TS — dropping + recreating public schema"
psql "$PG_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "[restore] $TS — restoring database from $DB_FILE"
gunzip -c "$DB_FILE" | pg_restore --no-owner --no-privileges -d "$PG_URL"

if [[ -f "$UPLOADS_FILE" ]]; then
  echo "[restore] $TS — restoring uploads tree to $(dirname "$UPLOADS_DIR")"
  rm -rf "$UPLOADS_DIR"
  tar -xzf "$UPLOADS_FILE" -C "$(dirname "$UPLOADS_DIR")"
else
  echo "[restore] $TS — no uploads archive (skipping)"
fi

echo "[restore] $TS — done. Verify with: alembic current"
