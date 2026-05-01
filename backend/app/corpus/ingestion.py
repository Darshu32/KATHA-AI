"""Stage 6 corpus ingester — extract → chunk → embed → DB.

Responsibilities
----------------
- Find-or-create the document row by ``(jurisdiction, title, edition)``.
- Wipe its existing chunks (CASCADE wouldn't drop the doc, so we
  delete chunks explicitly).
- Re-chunk the source.
- Embed the chunks (one batch call to the embedder).
- Insert the new chunks.
- Mark the document ``status="indexed"`` on success, ``"error"`` on
  failure.

Idempotency
-----------
Re-running the same ingest replaces every chunk under that document.
The document row is preserved (so its FK from anywhere else stays
valid). Re-ingesting with a *different* edition creates a new
document row — versions don't stomp each other.

Failure semantics
-----------------
- Empty document (zero chunks): ``IndexResult(chunk_count=0,
  skipped_reason="no_content")``. Document row is still upserted
  with ``status="indexed"`` so the caller can tell "we tried".
- Embedder fails: re-raises :class:`EmbeddingError`. The document
  row is marked ``status="error"`` first so the admin UI can show
  a re-try button.
- DB write fails: standard SQLAlchemy error bubbles up. Caller's
  transaction rolls back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.corpus.chunker import Chunk, chunk_document
from app.corpus.extractors.types import Document
from app.memory.embeddings import Embedder, EmbeddingError, get_embedder
from app.repositories.knowledge_corpus import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    document_id: str
    title: str
    jurisdiction: str
    chunk_count: int
    deleted_count: int
    embedder: str
    skipped_reason: Optional[str] = None


class CorpusIngester:
    """Stateless orchestrator — hold an embedder reference, delegate
    to repos for the storage layer."""

    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self._embedder = embedder or get_embedder()

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    async def ingest(
        self,
        session: AsyncSession,
        *,
        document: Document,
        storage_key: str = "",
    ) -> IngestResult:
        """Run the full pipeline. Returns a summary; never silently
        loses data."""
        # 1. Upsert the document row.
        doc_row = await KnowledgeDocumentRepository.upsert(
            session,
            jurisdiction=document.jurisdiction,
            title=document.title,
            source_type=document.source_type,
            publisher=document.publisher,
            edition=document.edition,
            total_pages=document.total_pages,
            language=document.language,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            storage_key=storage_key,
        )

        # 2. Wipe existing chunks for re-ingestion.
        deleted = await KnowledgeChunkRepository.delete_for_document(
            session, document_id=doc_row.id,
        )

        # 3. Chunk + embed.
        chunks: list[Chunk] = chunk_document(document)
        if not chunks:
            await KnowledgeDocumentRepository.mark_status(
                session, document_id=doc_row.id, status="indexed",
            )
            return IngestResult(
                document_id=doc_row.id,
                title=doc_row.title,
                jurisdiction=doc_row.jurisdiction,
                chunk_count=0,
                deleted_count=deleted,
                embedder=self._embedder.name,
                skipped_reason="no_content",
            )

        contents = [c.content for c in chunks]
        try:
            vectors = await self._embedder.embed_many(contents)
        except EmbeddingError:
            await KnowledgeDocumentRepository.mark_status(
                session, document_id=doc_row.id, status="error",
            )
            raise

        if len(vectors) != len(chunks):
            await KnowledgeDocumentRepository.mark_status(
                session, document_id=doc_row.id, status="error",
            )
            raise RuntimeError(
                f"Embedder returned {len(vectors)} vectors for {len(chunks)} "
                "chunks — refusing to insert mismatched rows"
            )

        # 4. Build payload + insert.
        payload: list[dict] = []
        for c, vec in zip(chunks, vectors):
            payload.append({
                "content": c.content,
                "embedding": vec,
                "page": c.page,
                "page_end": c.page_end,
                "section": c.section,
                "chunk_index": c.chunk_index,
                "total_chunks": c.total_chunks,
                "token_count": c.token_estimate,
                "metadata_": dict(c.extra or {}),
            })

        await KnowledgeChunkRepository.insert_chunks(
            session,
            document_id=doc_row.id,
            jurisdiction=doc_row.jurisdiction,
            chunks=payload,
        )

        # 5. Mark indexed.
        await KnowledgeDocumentRepository.mark_status(
            session, document_id=doc_row.id, status="indexed",
        )

        return IngestResult(
            document_id=doc_row.id,
            title=doc_row.title,
            jurisdiction=doc_row.jurisdiction,
            chunk_count=len(chunks),
            deleted_count=deleted,
            embedder=self._embedder.name,
        )
