"""Stage 6 — global RAG knowledge corpus.

The corpus is shared across every project + every user. The agent's
``search_knowledge`` tool queries it whenever an architect asks
something a code book or vendor catalog should answer:

    "What's the corridor width for a hospital?"
    → search_knowledge("hospital corridor width", jurisdiction="nbc_india_2016")
    → top hit: NBC Part 4 §3.2 chunk
    → answer cites verbatim with page reference

Public surface
--------------
- :class:`Document` / :class:`ExtractedPage` — extractor outputs
- :func:`extract_pdf`, :func:`extract_plain_text` — extractor entry points
- :func:`chunk_document` — semantic chunking with overlap + citation
- :class:`CorpusIngester` — orchestrator (extract → chunk → embed → DB)
- :class:`CorpusRetriever` — hybrid retrieval (vector ∪ BM25 → re-rank)
- :class:`SearchHit` — one ranked, fully-cited result
- :class:`Reranker` / :class:`NoopReranker` — optional cross-encoder seam

The agent-facing tools live in :mod:`app.agents.tools.knowledge_search`.
"""

from app.corpus.chunker import (
    Chunk,
    chunk_document,
)
from app.corpus.extractors.pdf import extract_pdf
from app.corpus.extractors.plain_text import extract_plain_text
from app.corpus.extractors.types import (
    Document,
    ExtractedPage,
    ExtractionError,
)
from app.corpus.ingestion import CorpusIngester, IngestResult
from app.corpus.re_ranker import NoopReranker, Reranker
from app.corpus.retriever import CorpusRetriever, SearchHit

__all__ = [
    "Chunk",
    "CorpusIngester",
    "CorpusRetriever",
    "Document",
    "ExtractedPage",
    "ExtractionError",
    "IngestResult",
    "NoopReranker",
    "Reranker",
    "SearchHit",
    "chunk_document",
    "extract_pdf",
    "extract_plain_text",
]
