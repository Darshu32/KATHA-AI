"""Stage 13 — index hygiene.

Adds defensive composite indexes covering query paths that grew
organically across stages 4-11 but never got dedicated indexes:

- ``audit_events`` lookup by (request_id, created_at) — Stage 11
  challenge → tool-call audit cross-references walk this path.
- ``chat_messages`` lookup by (chat_session_id, created_at) — chat
  history pagination is the hottest read in the system.
- ``project_memory_chunks`` lookup by (project_id, source_type,
  source_id) — Stage 5C re-indexing replaces by source; without
  this index the DELETE on re-index does a seq scan.
- ``estimate_snapshots`` lookup by (graph_version_id, created_at)
  — Stage 4 cost-history queries want the newest estimate per
  graph version cheaply.
- ``generated_assets`` lookup by (graph_version_id, created_at) —
  Stage 4 drawings/diagrams asset listing.

All ``CREATE INDEX IF NOT EXISTS`` because they're additive — a
re-run of a prior environment upgrades the schema without
duplicating work. PostgreSQL-specific syntax; we depend on PG
elsewhere already.

Revision ID: 0022_stage13_indexes
Revises: 0021_stage11_transparency
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op


revision = "0022_stage13_indexes"
down_revision = "0021_stage11_transparency"
branch_labels = None
depends_on = None


_INDEXES = [
    # name, table, columns
    (
        "ix_audit_events_request_recent",
        "audit_events",
        ["request_id", "created_at"],
    ),
    (
        "ix_chat_messages_session_recent",
        "chat_messages",
        ["chat_session_id", "created_at"],
    ),
    (
        "ix_project_memory_chunks_project_source",
        "project_memory_chunks",
        ["project_id", "source_type", "source_id"],
    ),
    (
        "ix_estimate_snapshots_graph_recent",
        "estimate_snapshots",
        ["graph_version_id", "created_at"],
    ),
    (
        "ix_generated_assets_graph_recent",
        "generated_assets",
        ["graph_version_id", "created_at"],
    ),
]


def upgrade() -> None:
    for index_name, table, columns in _INDEXES:
        # ``IF NOT EXISTS`` keeps re-runs idempotent across dev /
        # staging / prod where some envs may have ad-hoc indexes.
        cols_csv = ", ".join(columns)
        op.execute(
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{table}" ({cols_csv})'
        )


def downgrade() -> None:
    for index_name, _, _ in _INDEXES:
        op.execute(f'DROP INDEX IF EXISTS "{index_name}"')
