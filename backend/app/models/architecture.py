"""ORM models for structured architecture knowledge."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin, UUIDMixin


class ArchitectureSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "architecture_snapshots"

    repo_name: Mapped[str] = mapped_column(String(200), default="katha-ai")
    commit_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="ready")

    nodes: Mapped[list["ArchitectureNode"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    edges: Mapped[list["ArchitectureEdge"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    file_facts: Mapped[list["ArchitectureFileFact"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class ArchitectureNode(Base, UUIDMixin):
    __tablename__ = "architecture_nodes"

    snapshot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("architecture_snapshots.id"), index=True
    )
    node_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    file_path: Mapped[str] = mapped_column(String(512), default="")
    symbol_path: Mapped[str] = mapped_column(String(512), default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    snapshot: Mapped["ArchitectureSnapshot"] = relationship(back_populates="nodes")


class ArchitectureEdge(Base, UUIDMixin):
    __tablename__ = "architecture_edges"

    snapshot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("architecture_snapshots.id"), index=True
    )
    from_node_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("architecture_nodes.id"), index=True
    )
    to_node_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("architecture_nodes.id"), index=True
    )
    edge_type: Mapped[str] = mapped_column(String(64), index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    snapshot: Mapped["ArchitectureSnapshot"] = relationship(back_populates="edges")


class ArchitectureFileFact(Base, UUIDMixin):
    __tablename__ = "architecture_file_facts"

    snapshot_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("architecture_snapshots.id"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(512), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    snapshot: Mapped["ArchitectureSnapshot"] = relationship(back_populates="file_facts")
