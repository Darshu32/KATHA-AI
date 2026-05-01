"""SQLAlchemy ORM models — single source of truth for the relational schema."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# pgvector exposes ``Vector`` for SQLAlchemy. We import lazily so an env
# without pgvector installed can still import this module (the ORM
# class lookup will only fail when someone actually queries the chunk
# table). Falls back to a plain ARRAY-of-Float so SQLAlchemy can still
# produce the metadata for unit tests that never hit Postgres.
try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
    _PGVECTOR_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only on bare envs
    from sqlalchemy import ARRAY

    class Vector:  # type: ignore[no-redef]
        """Stub used when pgvector isn't installed.

        Resolves to ``ARRAY(Float)`` so the ORM still imports cleanly.
        Anything that actually executes a vector query raises later;
        we want the import to succeed because most of the codebase
        doesn't touch the chunk table.
        """

        def __new__(cls, dim: int):  # noqa: D401 — drop-in replacement
            return ARRAY(Float, dimensions=1)

    _PGVECTOR_AVAILABLE = False

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


class Design(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "designs"

    room_type: Mapped[str] = mapped_column(String(64), index=True)
    theme: Mapped[str] = mapped_column(String(32), index=True)
    dimensions: Mapped[dict] = mapped_column(JSONB, default=dict)
    requirements: Mapped[str] = mapped_column(Text)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="accepted", index=True
    )  # accepted | processing | completed | failed
    theme_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    concept_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    layout_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    drawing_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    render_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    estimate_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    pipeline_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    pipeline_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")


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

    graph_version: Mapped["DesignGraphVersion"] = relationship(
        back_populates="assets"
    )


# ── Chat sessions (Stage 5 — agent runtime memory) ───────────────────────────


class ChatSession(Base, UUIDMixin, TimestampMixin):
    """One ongoing agent conversation, optionally scoped to a project.

    A session is created when the user opens a chat (or, server-side,
    when ``/v2/chat`` is hit without an explicit ``session_id``).
    Subsequent turns append :class:`ChatMessage` rows. The agent loop
    reads the prior messages on each turn so the LLM sees continuity.

    Why scoped to a project (optional)
    ----------------------------------
    Most architect chats are *about* a specific project, so we key by
    ``project_id`` to make resumption + RAG tractable. Sessions can
    also be unscoped (``project_id=None``) for general / triage chats.
    """

    __tablename__ = "chat_sessions"

    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("projects.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(
        String(32), default="active"
    )  # active | archived
    last_message_at: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # Quick stats so the chat list view doesn't have to count rows.
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        order_by="ChatMessage.position",
        cascade="all, delete-orphan",
    )


class ChatMessage(Base, UUIDMixin, TimestampMixin):
    """One persisted turn in a chat session.

    Mirrors the :class:`AgentMessage` runtime type plus enough
    metadata to render a UI transcript (token usage, elapsed_ms,
    tool-call summaries) without re-deriving from the raw content.

    Roles
    -----
    - ``user``       — input from the architect.
    - ``assistant``  — text output from the LLM.
    - ``tool``       — JSON record of tool calls + results that
                       happened during the assistant turn. We store
                       these as separate rows (not nested) so the UI
                       can render them as inline cards.

    The ``content`` JSONB blob is the source of truth — it carries
    text + tool-use blocks Anthropic-style. Other columns are
    denormalised for indexing / display.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index(
            "ix_chat_messages_session_position",
            "session_id",
            "position",
            unique=True,
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | tool
    position: Mapped[int] = mapped_column(Integer)  # 1-based; unique per session

    content: Mapped[dict] = mapped_column(JSONB, default=dict)
    # ``content`` shape:
    #   {"type": "text", "text": "..."}
    #   {"type": "assistant", "blocks": [{text}|{tool_call}, ...]}
    #   {"type": "tool_results", "results": [{tool_call_id, ok, output|error}, ...]}

    # Display / index helpers (denormalised from content for fast list views).
    text_preview: Mapped[str] = mapped_column(Text, default="")
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


# ── Project memory (Stage 5B — RAG over project artefacts) ───────────────────


class ProjectMemoryChunk(Base, UUIDMixin, TimestampMixin):
    """One embedded chunk of project content.

    Sources we index:

    - ``design_version`` — a saved ``DesignGraphVersion`` (room, objects,
      materials, theme).
    - ``material_spec`` / ``manufacturing_spec`` / ``mep_spec`` — the
      structured spec sheet returned by the Stage 4D LLM authors.
    - ``cost_engine`` — a Stage 2 cost engine breakdown.
    - ``drawing`` / ``diagram`` — the LLM-authored spec (key dimensions,
      callouts, rationale) — we don't index the SVG bytes.

    The combination ``(project_id, source_type, source_id, source_version)``
    forms a logical key. Re-indexing the same source replaces every prior
    chunk for that key (delete + insert) so the table stays compact.

    The ``embedding`` column holds the OpenAI ``text-embedding-3-small``
    vector (1536 dims). Cosine distance is the search metric — matches
    OpenAI's recommendation for that model.
    """

    __tablename__ = "project_memory_chunks"
    __table_args__ = (
        Index(
            "ix_project_memory_logical_source",
            "project_id",
            "source_type",
            "source_id",
            "source_version",
        ),
        Index(
            "ix_project_memory_project_owner",
            "project_id",
            "owner_id",
        ),
    )

    # Project + owner scope. We carry owner_id explicitly so the
    # search query can cheap-filter without joining to ``projects``.
    project_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Source metadata.
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional: design-graph version number, snapshot index, etc.
    # Stored as a string for flexibility ("v3" / "snap_007").
    source_version: Mapped[str] = mapped_column(String(64), default="")

    # Chunk position within the source — useful for re-stitching long
    # sources back together when displaying a recall result.
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=1)

    # The text we actually embedded — kept verbatim so search results
    # carry the exact context the LLM saw at index time.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)

    # 1536-dim vector for OpenAI text-embedding-3-small.
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)

    # Free-form display metadata (title, summary, anchors). Used by
    # the agent UI to render a recall-result card.
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


# ── Uploaded assets (Stage 7 — multi-modal inputs) ───────────────────────────


class UploadedAsset(Base, UUIDMixin, TimestampMixin):
    """One uploaded binary asset — image, sketch, reference, etc.

    The bytes themselves live in the storage backend (local disk or
    S3 / R2). This row carries the metadata + storage key the agent
    layer needs to resolve them later.

    Lifecycle
    ---------
    1. Client POSTs to ``/v2/uploads`` (multipart form). Route
       creates the row with ``status='uploading'``.
    2. Storage backend writes the bytes; route flips ``status`` to
       ``ready`` on success or ``error`` on failure.
    3. Agent tools resolve assets by id, then call
       ``StorageBackend.get_bytes(storage_key)``.

    Why ``kind`` (not ``mime_type``) drives behaviour
    --------------------------------------------------
    A JPEG can be a site photo or a hand sketch — same MIME, very
    different vision-prompt shape. The route layer accepts a free
    ``kind`` slug that flows through to the agent's vision tools so
    the LLM gets the right purpose-specific prompt.
    """

    __tablename__ = "uploaded_assets"
    __table_args__ = (
        Index(
            "ix_uploaded_assets_owner_recent",
            "owner_id",
            "created_at",
        ),
    )

    owner_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Free-form kind slug — image | site_photo | reference |
    # mood_board | hand_sketch | existing_floor_plan | audio | other.
    # Drives vision tool prompt selection.
    kind: Mapped[str] = mapped_column(String(64), default="image")

    storage_backend: Mapped[str] = mapped_column(String(16), default="local")
    storage_key: Mapped[str] = mapped_column(String(512))

    original_filename: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(64), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")

    status: Mapped[str] = mapped_column(
        String(32),
        default="ready",
    )  # uploading | ready | error
    error_message: Mapped[str] = mapped_column(Text, default="")

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


# ── Knowledge Base / RAG corpus (Stage 6) ────────────────────────────────────


class KnowledgeDocument(Base, UUIDMixin, TimestampMixin):
    """One source document in the global knowledge corpus.

    Stage 6 — the corpus is **shared across all users + projects**.
    Every architect sees the same NBC, IBC, ECBC, vendor catalogs,
    etc. Documents are versioned via ``effective_from`` /
    ``effective_to`` so an updated NBC 2024 can supersede NBC 2016
    without losing the audit trail.
    """

    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(400))
    source_type: Mapped[str] = mapped_column(
        String(64)
    )  # pdf | manual | catalog | style_guide | textbook | bye_law
    storage_key: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | processing | indexed | error

    # Stage 6 additions — citation + jurisdiction.
    jurisdiction: Mapped[str] = mapped_column(
        String(64), default="", index=True,
    )  # e.g. nbc_india_2016 | ibc_us_2021 | ecbc_india | maharashtra_dcr | karnataka_kmc
    publisher: Mapped[str] = mapped_column(String(200), default="")
    edition: Mapped[str] = mapped_column(String(64), default="")
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(8), default="en")
    effective_from: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )  # ISO date string
    effective_to: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeChunk(Base, UUIDMixin):
    """One indexable chunk of a knowledge document.

    Stage 6 — each chunk carries:

    - The verbatim text (so search results are quotable).
    - An ``embedding vector(1536)`` for semantic similarity.
    - A ``content_tsv`` Postgres tsvector for BM25-like keyword
      matching. Built by a migration trigger on insert/update.
    - Citation metadata (page, section anchor) so the agent can
      answer "NBC Part 4 §3.2" instead of "we have a chunk that
      mentions corridor width".
    - ``jurisdiction`` denormalised from the parent document for
      cheap WHERE-filtering without a join.

    Re-ingesting a document deletes its chunks and writes new ones
    (CASCADE on the FK). The IDs are not stable across re-ingests;
    cite by ``(document_id, section, page)`` instead.
    """

    __tablename__ = "knowledge_chunks"

    document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
    )
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    # Stage 6 — citation metadata.
    jurisdiction: Mapped[str] = mapped_column(
        String(64), default="", index=True,
    )  # denormalised from parent document
    page: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(
        String(200), default="",
    )  # e.g. "Part 4 §3.2" / "Chapter 5 - Plumbing Fixtures"
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=1)

    # The embedding column. Migration 0017 ALTERs from a placeholder
    # type to ``vector(1536)`` after enabling the extension. We use
    # the same Vector wrapper as project_memory_chunks so a bare-
    # pgvector dev env can still import this module.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536), nullable=True,
    )

    # The keyword-search column — populated by a Postgres trigger on
    # insert/update from ``content``. Declared as deferred-loaded
    # JSONB-ish in the ORM (we never read it from Python; queries
    # use raw SQL ``ts_rank`` against this column).
    # Type left as ``Text`` here so SQLAlchemy doesn't try to validate
    # tsvector contents — the migration sets the actual type.
    # (Stage 6 — see migration 0017_stage6_corpus.py)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")
