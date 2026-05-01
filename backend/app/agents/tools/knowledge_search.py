"""Stage 6 agent tools — RAG search over the global knowledge corpus.

Two tools, both **read-only** so they're eligible for the Stage-5
parallel dispatcher:

- :func:`search_knowledge` — semantic + keyword hybrid search.
  Returns chunks with full citation metadata so the agent's reply
  can include verbatim references like "NBC India 2016 Part 4 §3.2".
- :func:`list_knowledge_sources` — what corpus the agent has access
  to. Lets the agent answer "do you know about ECBC?" without a
  search call.

Citation contract
-----------------
Every :class:`SearchHit` carries:

- ``content`` — the exact text that was indexed.
- ``source`` — human-readable (title + edition).
- ``page`` / ``page_end`` — numeric, matches the PDF.
- ``section`` — free-form anchor ("Part 4 §3.2", "Chapter 5 §503").
- ``jurisdiction`` — slug (``nbc_india_2016`` etc.).
- ``score`` — relevance in [0, 1] roughly.

The agent's system prompt (set in :mod:`app.agents.prompts.architect`)
instructs the LLM to **always cite** when it answers from a search
hit. The tool docstring repeats that hint to the LLM.

Both tools are global — they don't require a project_id. They do
need an authenticated user (the corpus is admin-curated; we don't
expose unauthenticated retrieval to the public).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.corpus import CorpusRetriever, SearchHit
from app.memory.embeddings import EmbeddingError
from app.repositories.knowledge_corpus import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 1. search_knowledge
# ─────────────────────────────────────────────────────────────────────


class SearchKnowledgeInput(BaseModel):
    query: str = Field(
        description=(
            "Natural-language question or topic — 'corridor width "
            "for hospital', 'IBC fire-rated wall thickness'. The "
            "retriever blends semantic similarity with keyword "
            "matching, so exact code references like 'NBC §3.2' "
            "land too."
        ),
        min_length=2,
        max_length=2000,
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Optional filter — restrict to one jurisdiction. Examples: "
            "'nbc_india_2016', 'ibc_us_2021', 'ecbc_india', "
            "'maharashtra_dcr', 'karnataka_kmc'. Omit to search the "
            "whole corpus. Use list_knowledge_sources to see what's "
            "indexed."
        ),
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "How many ranked hits to return. Default 5; cap 20. The "
            "retriever oversamples 4× internally before re-ranking."
        ),
    )


class CitedHit(BaseModel):
    """One ranked search result with the full citation contract."""

    chunk_id: str
    document_id: str
    content: str = Field(
        description="Verbatim text indexed from the source. Quote in citations.",
    )
    source: str = Field(description="Human-readable source label (title + edition).")
    jurisdiction: str
    page: int
    page_end: int
    section: str
    score: float
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    chunk_index: int = 0
    total_chunks: int = 1


class SearchKnowledgeOutput(BaseModel):
    query: str
    jurisdiction: Optional[str] = None
    embedder: str
    reranker: str
    returned_count: int
    hits: list[CitedHit]


def _require_actor(ctx: ToolContext) -> str:
    actor_id = ctx.actor_id
    if not actor_id:
        raise ToolError(
            "No actor_id on the agent context. Knowledge search "
            "requires an authenticated user — the corpus is admin-"
            "curated and we don't expose unauthenticated retrieval."
        )
    return actor_id


def _hit_to_cited(hit: SearchHit) -> CitedHit:
    return CitedHit(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        content=hit.content,
        source=hit.source,
        jurisdiction=hit.jurisdiction,
        page=hit.page,
        page_end=hit.page_end,
        section=hit.section,
        score=hit.score,
        vector_score=hit.vector_score,
        bm25_score=hit.bm25_score,
        chunk_index=hit.chunk_index,
        total_chunks=hit.total_chunks,
    )


@tool(
    name="search_knowledge",
    description=(
        "Hybrid semantic + keyword search over the global knowledge "
        "corpus (NBC India, IBC, ECBC, state bye-laws, vendor "
        "catalogs, architecture textbooks). Returns chunks with full "
        "citation metadata: source title, edition, page, section. "
        "Use whenever the architect asks something a code book or "
        "reference text should answer. **Always cite** the source, "
        "page, and section in the reply when you use a hit. "
        "Read-only."
    ),
    timeout_seconds=30.0,
)
async def search_knowledge(
    ctx: ToolContext,
    input: SearchKnowledgeInput,
) -> SearchKnowledgeOutput:
    _require_actor(ctx)

    retriever = CorpusRetriever()
    try:
        hits = await retriever.search(
            ctx.session,
            query=input.query,
            jurisdiction=input.jurisdiction,
            top_k=input.top_k,
        )
    except EmbeddingError as exc:
        raise ToolError(f"Embedding failed: {exc}") from exc
    except RuntimeError as exc:
        raise ToolError(f"Knowledge search unavailable: {exc}") from exc

    return SearchKnowledgeOutput(
        query=input.query,
        jurisdiction=input.jurisdiction,
        embedder=retriever.embedder.name,
        reranker=retriever.reranker.name,
        returned_count=len(hits),
        hits=[_hit_to_cited(h) for h in hits],
    )


# ─────────────────────────────────────────────────────────────────────
# 2. list_knowledge_sources
# ─────────────────────────────────────────────────────────────────────


class ListKnowledgeSourcesInput(BaseModel):
    jurisdiction: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional filter — list only docs in this jurisdiction.",
    )
    source_type: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "Optional filter — 'pdf' / 'manual' / 'catalog' / "
            "'style_guide' / 'textbook' / 'bye_law'."
        ),
    )


class CorpusSourceEntry(BaseModel):
    document_id: str
    title: str
    source_type: str
    jurisdiction: str
    publisher: str = ""
    edition: str = ""
    total_pages: int = 0
    language: str = "en"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: str
    chunk_count: int = 0


class ListKnowledgeSourcesOutput(BaseModel):
    total_documents: int
    total_chunks: int
    sources: list[CorpusSourceEntry]


@tool(
    name="list_knowledge_sources",
    description=(
        "List the documents currently indexed in the knowledge corpus. "
        "Returns title, jurisdiction, edition, page count, status, and "
        "chunk count per document. Use to answer 'what codes do you "
        "know about?' or to scope a follow-up search_knowledge call to "
        "a specific jurisdiction. Read-only."
    ),
    timeout_seconds=15.0,
)
async def list_knowledge_sources(
    ctx: ToolContext,
    input: ListKnowledgeSourcesInput,
) -> ListKnowledgeSourcesOutput:
    _require_actor(ctx)

    docs = await KnowledgeDocumentRepository.list_documents(
        ctx.session,
        jurisdiction=input.jurisdiction,
        source_type=input.source_type,
        status="indexed",
    )

    total_chunks = await KnowledgeChunkRepository.count(
        ctx.session,
        jurisdiction=input.jurisdiction,
    )

    # Per-doc chunk counts. We do this with one IN-list aggregate so
    # a corpus of dozens of documents still resolves in milliseconds.
    chunk_counts: dict[str, int] = {}
    if docs:
        from sqlalchemy import func, select
        from app.models.orm import KnowledgeChunk

        ids = [d.id for d in docs]
        result = await ctx.session.execute(
            select(
                KnowledgeChunk.document_id,
                func.count(KnowledgeChunk.id),
            )
            .where(KnowledgeChunk.document_id.in_(ids))
            .group_by(KnowledgeChunk.document_id)
        )
        chunk_counts = {row[0]: int(row[1] or 0) for row in result.all()}

    entries = [
        CorpusSourceEntry(
            document_id=d.id,
            title=d.title,
            source_type=d.source_type,
            jurisdiction=d.jurisdiction or "",
            publisher=d.publisher or "",
            edition=d.edition or "",
            total_pages=int(d.total_pages or 0),
            language=d.language or "en",
            effective_from=d.effective_from,
            effective_to=d.effective_to,
            status=d.status,
            chunk_count=chunk_counts.get(d.id, 0),
        )
        for d in docs
    ]

    return ListKnowledgeSourcesOutput(
        total_documents=len(entries),
        total_chunks=total_chunks,
        sources=entries,
    )
