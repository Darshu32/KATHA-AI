"""Stage 5B — project memory (RAG).

The agent's long-term store of *what's in this project*. The chat
session memory (Stage 5) covers the conversation; this layer covers
the artefacts the conversation produces — design versions, specs,
cost breakdowns, drawings, diagrams.

Public surface
--------------
- :class:`Embedder` / :func:`get_embedder` — OpenAI ``text-embedding-3-small``
  wrapper. Tests inject a stub via :class:`StubEmbedder`.
- :func:`chunk_text` and per-source-type chunkers — turn an artefact
  into one or more text chunks of a target token size.
- :class:`ProjectMemoryIndexer` — orchestrator: source → chunks →
  embeddings → DB rows. Idempotent.
- :class:`ProjectMemoryRetriever` — query → embedding → top-K results.

The agent-facing tools (``search_project_memory``, ``index_project_artefact``)
live in :mod:`app.agents.tools.memory` and call into this package.
"""

from app.memory.chunker import (
    chunk_cost_engine,
    chunk_design_version,
    chunk_drawing_or_diagram,
    chunk_spec_bundle,
    chunk_text,
)
from app.memory.embeddings import (
    Embedder,
    EmbeddingError,
    OpenAIEmbedder,
    StubEmbedder,
    get_embedder,
)
from app.memory.indexer import IndexResult, ProjectMemoryIndexer
from app.memory.retriever import ProjectMemoryRetriever, SearchHit

__all__ = [
    "Embedder",
    "EmbeddingError",
    "IndexResult",
    "OpenAIEmbedder",
    "ProjectMemoryIndexer",
    "ProjectMemoryRetriever",
    "SearchHit",
    "StubEmbedder",
    "chunk_cost_engine",
    "chunk_design_version",
    "chunk_drawing_or_diagram",
    "chunk_spec_bundle",
    "chunk_text",
    "get_embedder",
]
