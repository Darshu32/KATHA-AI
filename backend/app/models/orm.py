"""SQLAlchemy ORM models — single source of truth for the relational schema."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin, UUIDMixin


# ── Users ────────────────────────────────────────────────────────────────────


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


# ── Projects ─────────────────────────────────────────────────────────────────


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32), default="draft"
    )  # draft | generating | ready | archived
    latest_version: Mapped[int] = mapped_column(Integer, default=0)

    owner: Mapped["User"] = relationship(back_populates="projects")
    versions: Mapped[list["DesignGraphVersion"]] = relationship(
        back_populates="project", order_by="DesignGraphVersion.version"
    )


# ── Design Graph Versions ────────────────────────────────────────────────────


class DesignGraphVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "design_graph_versions"

    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("design_graph_versions.id"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(
        String(64), default="initial"
    )  # initial | prompt_edit | manual_edit | theme_switch | material_change
    change_summary: Mapped[str] = mapped_column(Text, default="")
    changed_object_ids: Mapped[list] = mapped_column(JSONB, default=list)

    # The full design graph snapshot (JSONB)
    graph_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    project: Mapped["Project"] = relationship(back_populates="versions")
    estimates: Mapped[list["EstimateSnapshot"]] = relationship(
        back_populates="graph_version"
    )
    assets: Mapped[list["GeneratedAsset"]] = relationship(
        back_populates="graph_version"
    )


# ── Estimates ────────────────────────────────────────────────────────────────


class EstimateSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "estimate_snapshots"

    graph_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("design_graph_versions.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | computed | error
    total_low: Mapped[float] = mapped_column(Float, default=0.0)
    total_high: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    assumptions: Mapped[dict] = mapped_column(JSONB, default=dict)

    graph_version: Mapped["DesignGraphVersion"] = relationship(
        back_populates="estimates"
    )
    line_items: Mapped[list["EstimateLineItem"]] = relationship(
        back_populates="snapshot"
    )


class EstimateLineItem(Base, UUIDMixin):
    __tablename__ = "estimate_line_items"

    snapshot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("estimate_snapshots.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(64))  # wall | floor | ceiling | fixture | furniture
    item_name: Mapped[str] = mapped_column(String(200))
    material: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(32), default="sqft")
    unit_rate_low: Mapped[float] = mapped_column(Float, default=0.0)
    unit_rate_high: Mapped[float] = mapped_column(Float, default=0.0)
    total_low: Mapped[float] = mapped_column(Float, default=0.0)
    total_high: Mapped[float] = mapped_column(Float, default=0.0)

    snapshot: Mapped["EstimateSnapshot"] = relationship(back_populates="line_items")


# ── Generated Assets ─────────────────────────────────────────────────────────


class GeneratedAsset(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "generated_assets"

    graph_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("design_graph_versions.id"), index=True
    )
    asset_type: Mapped[str] = mapped_column(
        String(32)
    )  # render_2d | scene_3d | mask | thumbnail
    storage_key: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(64), default="image/png")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


# ── Knowledge Base ───────────────────────────────────────────────────────────


class KnowledgeDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(400))
    source_type: Mapped[str] = mapped_column(
        String(64)
    )  # pdf | manual | catalog | style_guide
    storage_key: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | processing | indexed | error

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document")


class KnowledgeChunk(Base, UUIDMixin):
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_documents.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # pgvector column added via migration: embedding vector(1536)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")
