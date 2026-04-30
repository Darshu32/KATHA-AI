"""Baseline schema — first real migration after Stage 0.

Captures the entire current ORM schema (users, projects, designs, design
graph versions, estimates, generated assets, knowledge base, architecture
snapshots) plus the brand-new ``audit_events`` table introduced in Stage 0.

Note
----
Prior to Stage 0, the application bootstrapped its schema via
``Base.metadata.create_all`` in ``main.py`` lifespan. That has been removed
in the same change that introduces this migration. Existing dev databases
should be re-created or stamped with::

    alembic stamp 0001_baseline

if their schema already matches.

Revision ID: 0001_baseline
Revises: -
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector — enabled here because knowledge_chunks.embedding will use it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Users ────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── Projects ─────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    # ── Designs (legacy single-design entity, retained for compatibility) ─
    op.create_table(
        "designs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("room_type", sa.String(64), nullable=False),
        sa.Column("theme", sa.String(32), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column("budget", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="accepted"),
        sa.Column("theme_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("concept_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("layout_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("drawing_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("render_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("estimate_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("pipeline_state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("pipeline_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_designs_room_type", "designs", ["room_type"])
    op.create_index("ix_designs_theme", "designs", ["theme"])
    op.create_index("ix_designs_status", "designs", ["status"])

    # ── Design Graph Versions ────────────────────────────────────────────
    op.create_table(
        "design_graph_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "parent_version_id",
            sa.String(32),
            sa.ForeignKey("design_graph_versions.id"),
            nullable=True,
        ),
        sa.Column("change_type", sa.String(64), nullable=False, server_default="initial"),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("changed_object_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("graph_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_design_graph_versions_project_id", "design_graph_versions", ["project_id"])

    # ── Estimates ────────────────────────────────────────────────────────
    op.create_table(
        "estimate_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "graph_version_id",
            sa.String(32),
            sa.ForeignKey("design_graph_versions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("total_low", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_high", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_estimate_snapshots_graph_version_id", "estimate_snapshots", ["graph_version_id"])

    op.create_table(
        "estimate_line_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(32),
            sa.ForeignKey("estimate_snapshots.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("item_name", sa.String(200), nullable=False),
        sa.Column("material", sa.String(200), nullable=False, server_default=""),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(32), nullable=False, server_default="sqft"),
        sa.Column("unit_rate_low", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit_rate_high", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_low", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_high", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_estimate_line_items_snapshot_id", "estimate_line_items", ["snapshot_id"])

    # ── Generated Assets ─────────────────────────────────────────────────
    op.create_table(
        "generated_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "graph_version_id",
            sa.String(32),
            sa.ForeignKey("design_graph_versions.id"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False, server_default="image/png"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_generated_assets_graph_version_id", "generated_assets", ["graph_version_id"])

    # ── Knowledge Base ───────────────────────────────────────────────────
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(32),
            sa.ForeignKey("knowledge_documents.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    # pgvector embedding column on knowledge_chunks.
    # Stage 6 (RAG) will switch this to ivfflat/HNSW indexing once corpus exists.
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1536)"
    )

    # ── Architecture Snapshots (codebase introspection) ──────────────────
    op.create_table(
        "architecture_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("repo_name", sa.String(200), nullable=False, server_default="katha-ai"),
        sa.Column("commit_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "architecture_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(32),
            sa.ForeignKey("architecture_snapshots.id"),
            nullable=False,
        ),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("symbol_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_architecture_nodes_snapshot_id", "architecture_nodes", ["snapshot_id"])
    op.create_index("ix_architecture_nodes_node_type", "architecture_nodes", ["node_type"])
    op.create_index("ix_architecture_nodes_name", "architecture_nodes", ["name"])

    op.create_table(
        "architecture_edges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(32),
            sa.ForeignKey("architecture_snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "from_node_id",
            sa.String(32),
            sa.ForeignKey("architecture_nodes.id"),
            nullable=False,
        ),
        sa.Column(
            "to_node_id",
            sa.String(32),
            sa.ForeignKey("architecture_nodes.id"),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_architecture_edges_snapshot_id", "architecture_edges", ["snapshot_id"])
    op.create_index("ix_architecture_edges_from_node_id", "architecture_edges", ["from_node_id"])
    op.create_index("ix_architecture_edges_to_node_id", "architecture_edges", ["to_node_id"])
    op.create_index("ix_architecture_edges_edge_type", "architecture_edges", ["edge_type"])

    op.create_table(
        "architecture_file_facts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(32),
            sa.ForeignKey("architecture_snapshots.id"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_architecture_file_facts_snapshot_id",
        "architecture_file_facts",
        ["snapshot_id"],
    )
    op.create_index(
        "ix_architecture_file_facts_file_path",
        "architecture_file_facts",
        ["file_path"],
    )

    # ── Audit Events (new in Stage 0) ────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "actor_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_kind", sa.String(64), nullable=False, server_default="user"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("after", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_audit_events_target_history",
        "audit_events",
        ["target_type", "target_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_actor_recent",
        "audit_events",
        ["actor_id", "created_at"],
    )
    op.create_index("ix_audit_events_actor_kind", "audit_events", ["actor_kind"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])


def downgrade() -> None:
    # Reverse order to respect FK dependencies.
    op.drop_table("audit_events")
    op.drop_table("architecture_file_facts")
    op.drop_table("architecture_edges")
    op.drop_table("architecture_nodes")
    op.drop_table("architecture_snapshots")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("generated_assets")
    op.drop_table("estimate_line_items")
    op.drop_table("estimate_snapshots")
    op.drop_table("design_graph_versions")
    op.drop_table("designs")
    op.drop_table("projects")
    op.drop_table("users")
    # Leave the `vector` extension installed; it's harmless and may be used
    # by other tables/migrations.
