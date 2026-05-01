"""Stage 5B agent tools — project memory (RAG).

Two tools that surface project memory to the agent:

- :func:`search_project_memory` (read) — semantic search over a
  project's indexed artefacts. Use this when the architect references
  something earlier ("what did we say about the kitchen lighting?",
  "recall the cost we got last week") and the working context can't
  surface it cheaply.
- :func:`index_project_artefact` (write) — index a specific artefact
  the agent just produced. Use after generating a design version,
  building a spec bundle, or running the cost engine. The body of
  the artefact is supplied as a dict (the agent passes through the
  output of its prior tool call).

Both tools are project-scoped via ``ctx.project_id`` and
``ctx.actor_id``. ``search_project_memory`` filters on ``owner_id``
so the LLM cannot accidentally read another user's memory even if a
project_id is somehow leaked.

Cost guardrails
---------------
- Search timeout: 30 s (one OpenAI embedding call + one DB query).
- Index timeout: 60 s (embedding can be slower with multiple chunks).
- ``top_k`` clamped at the schema layer to 1..20.
- ``content_*`` payloads capped at 32 KB each — past that we expect
  the caller to chunk client-side or use ``index_design_version``
  via the higher-level pipeline tools.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.agents.tool import ToolContext, ToolError, tool
from app.memory import (
    EmbeddingError,
    ProjectMemoryIndexer,
    ProjectMemoryRetriever,
)
from app.repositories.project_memory import ProjectMemoryRepository

logger = logging.getLogger(__name__)


# Source-type slugs the indexer + chunker know about. The agent picks
# from this enum when calling ``index_project_artefact``.
_INDEXABLE_KINDS = {
    "design_version",
    "spec_bundle",
    "cost_engine",
    # Drawing kinds (Stage 4E ids, used as source_type slugs).
    "plan_view",
    "elevation_view",
    "section_view",
    "detail_sheet",
    "isometric_view",
    # Diagram kinds (Stage 4F ids).
    "concept_transparency",
    "form_development",
    "volumetric_hierarchy",
    "volumetric_block",
    "design_process",
    "solid_void",
    "spatial_organism",
    "hierarchy",
}


def _require_project(ctx: ToolContext) -> str:
    project_id = ctx.project_id
    if not project_id:
        raise ToolError(
            "No project_id on the agent context. Project memory tools "
            "require a project scope — open a project first or pass "
            "project_id when starting the chat session."
        )
    return project_id


def _require_owner(ctx: ToolContext) -> str:
    actor_id = ctx.actor_id
    if not actor_id:
        raise ToolError(
            "No actor_id on the agent context. Project memory tools "
            "require an authenticated user — they refuse to run as "
            "an anonymous session."
        )
    return actor_id


# ─────────────────────────────────────────────────────────────────────
# 1. search_project_memory
# ─────────────────────────────────────────────────────────────────────


class SearchProjectMemoryInput(BaseModel):
    """LLM input for project-memory search."""

    query: str = Field(
        description=(
            "Natural-language question or topic to search for — "
            "'kitchen island materials', 'last cost estimate for the "
            "modern variant', 'what dimensions did we set for the "
            "dining room'. Free-form text; the embedder maps it onto "
            "the indexed corpus."
        ),
        min_length=2,
        max_length=2000,
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "How many ranked hits to return. Default 5; cap 20 to "
            "keep token cost predictable."
        ),
    )
    source_type: Optional[str] = Field(
        default=None,
        description=(
            "Optional filter — restrict to one source kind. Examples: "
            "'design_version', 'spec_bundle', 'cost_engine', "
            "'plan_view', 'elevation_view', 'concept_transparency'. "
            "Omit to search everything."
        ),
    )

    @field_validator("source_type")
    @classmethod
    def _known_source_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in _INDEXABLE_KINDS:
            # Don't reject — the underlying table may have other
            # kinds — but we keep the API surface tight via a docstring
            # enumeration. Pass through.
            return v
        return v


class SearchHitOut(BaseModel):
    source_type: str
    source_id: str
    source_version: str
    chunk_index: int
    total_chunks: int
    content: str
    score: float = Field(
        description=(
            "Cosine similarity in [-1, 1]. 1.0 = identical, 0.0 = "
            "unrelated. Treat ≥ 0.7 as a confident hit; < 0.3 as weak."
        ),
    )
    distance: float = Field(
        description="Raw cosine distance (1 - score). Closer to 0 = better match.",
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchProjectMemoryOutput(BaseModel):
    project_id: str
    query: str
    returned_count: int
    embedder: str = Field(description="Embedder name (openai | stub).")
    hits: list[SearchHitOut]


@tool(
    name="search_project_memory",
    description=(
        "Semantic search over the current project's indexed artefacts "
        "(design versions, spec bundles, cost runs, drawings, "
        "diagrams). Returns the top-K most-relevant chunks with "
        "cosine similarity scores. Use when the architect references "
        "something earlier in the project that isn't in working "
        "context. Read-only; requires a project + an authenticated "
        "user."
    ),
    timeout_seconds=30.0,
)
async def search_project_memory(
    ctx: ToolContext,
    input: SearchProjectMemoryInput,
) -> SearchProjectMemoryOutput:
    project_id = _require_project(ctx)
    owner_id = _require_owner(ctx)

    retriever = ProjectMemoryRetriever()
    try:
        hits = await retriever.search(
            ctx.session,
            project_id=project_id,
            query=input.query,
            owner_id=owner_id,
            source_type=input.source_type,
            top_k=input.top_k,
        )
    except EmbeddingError as exc:
        raise ToolError(f"Embedding failed: {exc}") from exc
    except RuntimeError as exc:
        # pgvector unavailable / column type mismatch / etc.
        raise ToolError(f"Memory search unavailable: {exc}") from exc

    return SearchProjectMemoryOutput(
        project_id=project_id,
        query=input.query,
        returned_count=len(hits),
        embedder=retriever.embedder.name,
        hits=[
            SearchHitOut(
                source_type=h.source_type,
                source_id=h.source_id,
                source_version=h.source_version,
                chunk_index=h.chunk_index,
                total_chunks=h.total_chunks,
                content=h.content,
                score=h.score,
                distance=h.distance,
                extra=h.extra,
            )
            for h in hits
        ],
    )


# ─────────────────────────────────────────────────────────────────────
# 2. index_project_artefact
# ─────────────────────────────────────────────────────────────────────


class IndexProjectArtefactInput(BaseModel):
    """LLM input for explicit indexing."""

    kind: str = Field(
        description=(
            "Source kind — one of: 'design_version', 'spec_bundle', "
            "'cost_engine', 'plan_view', 'elevation_view', "
            "'section_view', 'detail_sheet', 'isometric_view', "
            "'concept_transparency', 'form_development', "
            "'volumetric_hierarchy', 'volumetric_block', "
            "'design_process', 'solid_void', 'spatial_organism', "
            "'hierarchy'."
        ),
        max_length=64,
    )
    source_id: str = Field(
        description=(
            "Stable id for this artefact — the version_id for design "
            "versions, the snapshot_id for cost runs, the LLM-assigned "
            "id for drawings/diagrams."
        ),
        min_length=1,
        max_length=120,
    )
    source_version: str = Field(
        default="",
        max_length=64,
        description="Optional version label (e.g. 'v3'). Omit when not applicable.",
    )
    body: dict[str, Any] = Field(
        description=(
            "The artefact body. Shape depends on ``kind``: a "
            "design_graph dict for 'design_version', a spec bundle for "
            "'spec_bundle', a cost_engine dict for 'cost_engine', a "
            "drawing/diagram spec for the visual kinds. The Stage 4 "
            "tools' outputs are designed to feed straight into here."
        ),
    )
    title: str = Field(
        default="",
        max_length=200,
        description="Optional display title for the recall card.",
    )
    theme: str = Field(default="", max_length=64)


class IndexProjectArtefactOutput(BaseModel):
    project_id: str
    source_type: str
    source_id: str
    source_version: str
    chunk_count: int
    deleted_count: int
    embedder: str
    skipped_reason: Optional[str] = None


@tool(
    name="index_project_artefact",
    description=(
        "Index an artefact into project memory so the agent can recall "
        "it later via search_project_memory. Idempotent — re-indexing "
        "the same source replaces the prior chunks. Use after "
        "generating a design version, building a spec bundle, running "
        "the cost engine, or producing a drawing/diagram. Requires "
        "a project + authenticated user."
    ),
    timeout_seconds=60.0,
    audit_target_type="project_memory",
)
async def index_project_artefact(
    ctx: ToolContext,
    input: IndexProjectArtefactInput,
) -> IndexProjectArtefactOutput:
    project_id = _require_project(ctx)
    owner_id = _require_owner(ctx)

    indexer = ProjectMemoryIndexer()

    kind = input.kind.strip()
    body = input.body or {}

    try:
        if kind == "design_version":
            # Best-effort version int (default 0 if not parseable).
            version_int = 0
            try:
                version_int = int(input.source_version.lstrip("v") or "0")
            except (TypeError, ValueError):
                version_int = 0
            result = await indexer.index_design_version(
                ctx.session,
                project_id=project_id,
                owner_id=owner_id,
                version_id=input.source_id,
                version=version_int,
                graph_data=body,
                project_name=input.title,
            )
        elif kind == "spec_bundle":
            version_int = 0
            try:
                version_int = int(input.source_version.lstrip("v") or "0")
            except (TypeError, ValueError):
                version_int = 0
            result = await indexer.index_spec_bundle(
                ctx.session,
                project_id=project_id,
                owner_id=owner_id,
                version_id=input.source_id,
                version=version_int,
                bundle=body,
                project_name=input.title,
            )
        elif kind == "cost_engine":
            result = await indexer.index_cost_engine(
                ctx.session,
                project_id=project_id,
                owner_id=owner_id,
                snapshot_id=input.source_id,
                cost_engine=body,
            )
        elif kind in _INDEXABLE_KINDS:
            # Drawing or diagram.
            result = await indexer.index_drawing_or_diagram(
                ctx.session,
                project_id=project_id,
                owner_id=owner_id,
                kind=kind,
                artefact_id=input.source_id,
                spec=body,
                title=input.title,
                theme=input.theme,
                version=input.source_version,
            )
        else:
            raise ToolError(
                f"Unknown artefact kind {kind!r}. Allowed: "
                f"{sorted(_INDEXABLE_KINDS)}."
            )
    except EmbeddingError as exc:
        raise ToolError(f"Embedding failed: {exc}") from exc

    return IndexProjectArtefactOutput(
        project_id=result.project_id,
        source_type=result.source_type,
        source_id=result.source_id,
        source_version=result.source_version,
        chunk_count=result.chunk_count,
        deleted_count=result.deleted_count,
        embedder=result.embedding_model,
        skipped_reason=result.skipped_reason,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. project_memory_stats (lightweight read)
# ─────────────────────────────────────────────────────────────────────


class ProjectMemoryStatsInput(BaseModel):
    pass


class ProjectMemoryStatsOutput(BaseModel):
    project_id: str
    chunk_count: int


@tool(
    name="project_memory_stats",
    description=(
        "Return a quick summary of the current project's memory — "
        "how many chunks have been indexed. Useful as a sanity check "
        "before / after running index_project_artefact, or to decide "
        "whether to spend a search call. Requires a project."
    ),
    timeout_seconds=15.0,
)
async def project_memory_stats(
    ctx: ToolContext,
    input: ProjectMemoryStatsInput,
) -> ProjectMemoryStatsOutput:
    project_id = _require_project(ctx)
    count = await ProjectMemoryRepository.count_for_project(
        ctx.session, project_id=project_id,
    )
    return ProjectMemoryStatsOutput(project_id=project_id, chunk_count=count)


# ─────────────────────────────────────────────────────────────────────
# 4. prune_project_memory  (Stage 5D)
# ─────────────────────────────────────────────────────────────────────


class PruneProjectMemoryInput(BaseModel):
    """Inputs for an eviction sweep."""

    keep_latest_versions: int = Field(
        default=10,
        ge=1,
        le=200,
        description=(
            "How many of the most-recent design versions to keep. "
            "Older versions' chunks are dropped. Default 10. Capped "
            "at 200 — anything more should re-index from scratch "
            "via the per-version tools."
        ),
    )


class PruneProjectMemoryOutput(BaseModel):
    project_id: str
    keep_latest_versions: int
    removed_count: int
    chunks_remaining: int


@tool(
    name="prune_project_memory",
    description=(
        "Drop project-memory chunks for older design versions, "
        "keeping the latest N. Use to keep memory bounded after a "
        "long-running project accumulates dozens of design versions. "
        "Only design_version chunks are pruned — spec / cost / "
        "drawing / diagram chunks are left alone. Requires a project."
    ),
    timeout_seconds=30.0,
    audit_target_type="project_memory",
)
async def prune_project_memory(
    ctx: ToolContext,
    input: PruneProjectMemoryInput,
) -> PruneProjectMemoryOutput:
    project_id = _require_project(ctx)

    removed = await ProjectMemoryRepository.prune_old_design_versions(
        ctx.session,
        project_id=project_id,
        keep_latest=input.keep_latest_versions,
    )
    remaining = await ProjectMemoryRepository.count_for_project(
        ctx.session, project_id=project_id,
    )

    return PruneProjectMemoryOutput(
        project_id=project_id,
        keep_latest_versions=input.keep_latest_versions,
        removed_count=removed,
        chunks_remaining=remaining,
    )
