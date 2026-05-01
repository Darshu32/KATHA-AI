# Stage 6 — RAG Knowledge Corpus

> **Audience:** future-you ingesting a new code book, debugging a
> citation, switching the embedder, or wiring a real cross-encoder.
> Read after `docs/agents/memory.md`.

---

## What Stage 6 added

The agent can now answer code-and-spec questions by **searching real
source documents**, not just the structured tables in
`app.knowledge`. When the architect asks _"What's the corridor width
for a hospital?"_, the loop:

1. Calls `search_knowledge("hospital corridor width", jurisdiction="nbc_india_2016")`.
2. The retriever runs vector search + BM25 in parallel, merges the
   candidate set, optionally re-ranks.
3. Returns the top chunks with **full citation metadata**: source
   title, edition, page number, section anchor.
4. The system prompt instructs the LLM to cite — answers come back
   as "NBC India 2016 Part 4 §3.2 (page 47): _Corridor widths shall
   be a minimum of 1500 mm in hospitals…_".

```
                 ┌─────────────────────────────────────────────────────────┐
                 │                  agent loop                             │
                 └─┬───────────────────────────────────────────────────────┘
                   │
       search_knowledge(query, jurisdiction=…, top_k=…)
                   │
                   ▼
            CorpusRetriever
                   │
                   │   embed(query)  ────►   Embedder
                   │   ◄───────────  vec[1536]
                   │
                   ├──── vector_search(top_N)  ─►  pgvector cosine
                   ├──── keyword_search(top_N) ─►  GIN tsvector  (concurrent)
                   │
                   │   _hybrid_merge(α=0.7 vec + 0.3 bm25)
                   │
                   ▼
                Reranker (NoopReranker by default;
                          plug in cross-encoder for prod)
                   │
                   ▼
             SearchHit[] with citation contract
```

---

## Module map

```
backend/app/
├── corpus/                                  NEW package
│   ├── __init__.py                          Public API
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── types.py                         Document / ExtractedPage / ExtractionError
│   │   ├── pdf.py                           PyMuPDF wrapper (lazy import)
│   │   └── plain_text.py                    .txt / .md fallback (form-feed split)
│   ├── chunker.py                           Page-aware chunker with overlap + section anchors
│   ├── ingestion.py                         CorpusIngester (extract → chunk → embed → DB)
│   ├── retriever.py                         CorpusRetriever (hybrid + re-rank)
│   └── re_ranker.py                         Reranker ABC + NoopReranker default
├── repositories/knowledge_corpus/           NEW package
│   ├── __init__.py
│   ├── document_repo.py                     KnowledgeDocumentRepository
│   └── chunk_repo.py                        KnowledgeChunkRepository (vector + BM25 search)
├── agents/tools/knowledge_search.py         NEW — 2 agent tools
└── models/orm.py                            extended KnowledgeChunk + KnowledgeDocument

backend/alembic/versions/0017_stage6_corpus.py  ALTER tables + tsvector trigger + indexes
backend/requirements.txt                        + PyMuPDF==1.24.13
```

---

## Schema

`knowledge_documents` (extended)

| Column | Notes |
|---|---|
| `id`, `title`, `source_type`, `storage_key`, `status`, `created_at`, `updated_at` | Pre-existing |
| `jurisdiction` | Slug — `nbc_india_2016` / `ibc_us_2021` / `ecbc_india` / `maharashtra_dcr` / etc. |
| `publisher` | "BIS", "ICC", etc. |
| `edition` | "2016", "2021", "Volume 2 Rev. 5" |
| `total_pages` | Set during ingest |
| `language` | ISO-639 ("en", "hi") |
| `effective_from`, `effective_to` | ISO date strings — old NBC editions stay queryable but flagged |

`knowledge_chunks` (extended)

| Column | Notes |
|---|---|
| `id`, `document_id`, `content`, `token_count`, `metadata`, `created_at` | Pre-existing |
| `jurisdiction` | Denormalised from parent — cheap WHERE filter without a join |
| `page`, `page_end` | The source-page range this chunk spans |
| `section` | Free-form anchor — "Part 4 §3.2" / "Chapter 5 - Plumbing Fixtures" |
| `chunk_index`, `total_chunks` | Position within the document |
| `embedding` | `vector(1536)` — OpenAI `text-embedding-3-small` |
| `content_tsv` | `tsvector` — populated by trigger from `content`, GIN-indexed |

Indexes:

- IVFFlat `(embedding)` `vector_cosine_ops`, `lists=100` — vector search
- GIN `(content_tsv)` — BM25-like keyword search
- `(jurisdiction)` — cheap filter
- `(document_id, section)` — citation lookup
- FK `document_id` → `knowledge_documents.id` `ON DELETE CASCADE`

The trigger that maintains `content_tsv` on insert/update lives in
the migration: `to_tsvector('english', content)`. Switching to
multilingual support means a different config + a re-index.

---

## Citation contract

Every `SearchHit` carries:

```python
SearchHit(
  chunk_id="...",          # stable until re-ingestion
  document_id="...",
  content="Corridor widths shall be a minimum of 1500 mm…",
  source="NBC India 2016 (2016)",
  jurisdiction="nbc_india_2016",
  page=47,
  page_end=47,
  section="Part 4 §3.2",
  score=0.84,              # final hybrid + re-rank score in [0, 1]
  vector_score=0.91,       # raw vector similarity
  bm25_score=0.62,         # raw ts_rank_cd
  chunk_index=12,
  total_chunks=187,
  extra={...},             # display metadata
)
```

The agent's system prompt instructs the LLM:

> When answering from a `search_knowledge` hit, **always cite** the
> source title, edition, page, and section. Use the verbatim
> quotation in `content` rather than paraphrasing.

Non-citation answers from these tools are a code review bug.

---

## Hybrid retrieval

Vector and BM25 each contribute candidates from independent indexes.
The retriever merges them with a fixed weight:

```
final_score = 0.7 × vector_norm + 0.3 × bm25_norm
```

Both sides are min-max normalised before mixing so the alpha
actually means what it says. Identical-on-both-sides chunks get
deduped (max).

**Why these weights:** vector picks up paraphrases ("corridor for
hospitals" → "hospital passageway clearance"); BM25 picks up exact
code references ("§503.1") and rare technical terms. 0.7 / 0.3
keeps semantic recall as the dominant signal while still surfacing
exact-match queries.

The merge is over-sampled: if `top_k=5`, we pull 20 from each side
before re-ranking down to 5 — gives the re-ranker richer ground to
work with.

---

## Re-ranking

Stage 6 ships with `NoopReranker` — no-op, just truncates the merged
list to `top_k` in score-descending order. Production swaps in a
real cross-encoder via dependency injection:

```python
class MyCrossEncoder(Reranker):
    name = "ms-marco-MiniLM-L-12-v2"
    async def rerank(self, query, candidates, *, top_k=5):
        # batch (query, content) pairs through the model …
        # return new RerankCandidate list, truncated to top_k

retriever = CorpusRetriever(reranker=MyCrossEncoder())
```

`sentence-transformers` is the obvious starting point — pulls in
PyTorch (~80 MB model weights). Out of scope for Stage 6 because
the install footprint is heavy and most queries return decent
results from the hybrid blend alone.

---

## Embedders

Reused from Stage 5B (`app.memory.embeddings`):

- `OpenAIEmbedder` — `text-embedding-3-small`, 1536 dims, the prod path.
- `StubEmbedder` — deterministic hash → 1536-dim vector. Used in tests
  + when `OPENAI_API_KEY` is not set.

Both produce 1536-dim vectors so the schema doesn't change between
modes. `StubEmbedder` doesn't model semantics, but the BM25 path
still works against the tsvector index — so even without an OpenAI
key, exact-keyword queries succeed.

---

## Ingestion

```python
from app.corpus import CorpusIngester, extract_pdf

doc = extract_pdf(
    source_id="nbc-india-2016",
    title="National Building Code of India",
    payload=open("nbc_2016.pdf", "rb").read(),
    jurisdiction="nbc_india_2016",
    publisher="BIS",
    edition="2016",
    effective_from="2016-12-19",
)

ingester = CorpusIngester()  # default: OpenAI embedder
async with async_session_factory() as db:
    result = await ingester.ingest(db, document=doc)
    await db.commit()

print(result.chunk_count, "chunks indexed")
```

### Idempotency

The ingester:

1. **Upserts** the document row keyed on `(jurisdiction, title, edition)`.
2. **Wipes** every chunk under that document via
   `KnowledgeChunkRepository.delete_for_document`.
3. **Re-chunks** the source.
4. **Embeds** all chunks in one batch call.
5. **Inserts** the new chunks.
6. Marks the document `status="indexed"` (or `"error"` on failure).

Re-ingesting with a *different* edition creates a new document row.
Old editions stay queryable but can be filtered via
`effective_from / effective_to`.

### Failure modes

| Condition | Outcome |
|---|---|
| Empty document | `chunk_count=0`, `skipped_reason="no_content"`. Document row marked `indexed`. |
| Embedder raises | Document marked `status="error"`, `EmbeddingError` re-raised. Chunks left untouched (delete-then-insert is in the same transaction). |
| DB write fails | SQLAlchemy error bubbles up; transaction rolls back. |
| Embedder returns wrong vector count | `RuntimeError`, document marked `error`. |

---

## Initial corpus (deferred)

Stage 6 ships the **machinery**. Loading the actual NBC, IBC, ECBC,
state bye-laws, vendor catalogs, and Neufert is corpus-management
work that follows real procurement of source PDFs. The plan calls
for:

1. **NBC 2016** — full document (BIS-licensed PDF).
2. **IBC** — relevant chapters only (Chapters 5, 7, 9, 10).
3. **ECBC** — full energy code.
4. **Maharashtra DCR + Karnataka KMC** — state-specific bye-laws.
5. **Time Saver Standards / Neufert** — architecture textbook.
6. **Jaquar / Kohler / Asian Paints** — 2–3 vendor catalogs.

Each source file gets a row in an admin-only ingestion log; the
pipeline is the same `CorpusIngester` flow. Re-ingesting a new
edition uses the same `(jurisdiction, title, edition)` key + a
fresh `effective_from`.

### Jurisdictional priorities

When two sources cover the same topic (e.g. corridor width in NBC
*and* the Maharashtra DCR), the agent should prefer the most
specific jurisdiction. Stage 6 doesn't enforce this in the
retriever — the agent's system prompt handles the ranking via the
hits' `jurisdiction` field. A future stage may add a deterministic
priority filter.

---

## Test gate (deferred — needs real corpus)

The Stage 6 plan calls for a 50-question golden query set with
expected source matches and:

- **Recall@5 > 80%** — the right chunk must appear in the top-5
  hits for ≥ 40 / 50 queries.
- **Citation accuracy** — spot-check 20 answers; every cited page
  number must match the source PDF.

This needs the real corpus loaded first. The Stage 6 test surface
exercises the retrieval *machinery* end-to-end with synthetic code
excerpts:

- `tests/unit/test_stage6_chunker.py` — chunk boundaries, page
  tracking, section propagation, heading heuristics, agent tool
  registry shape.
- `tests/unit/test_stage6_retriever.py` — score normalisation,
  hybrid blend, NoopReranker truncation, retriever config.
- `tests/integration/test_stage6_rag.py` — full ingest → search
  round-trip against real Postgres + pgvector + tsvector. Citation
  contract verified end-to-end.

---

## What's *not* here yet

- **Cross-encoder re-ranking.** Seam built (`Reranker` ABC); default
  is `NoopReranker`. Plug `sentence-transformers/ms-marco-MiniLM-L-12-v2`
  into `CorpusRetriever(reranker=...)` when ready.
- **Real corpus.** Source PDFs need to be procured + ingested. The
  `CorpusIngester` is ready when they arrive.
- **Admin upload route.** `POST /v2/corpus/ingest` is a small wrapper
  around `CorpusIngester` — easy to add when the admin UI lands.
- **Multilingual support.** The trigger uses
  `to_tsvector('english', ...)`. Hindi / regional languages need a
  different FTS config + re-index.
- **Background-job ingestion.** Big PDFs (NBC is ~1500 pages) are
  worth backgrounding. Add a Celery task analogous to Stage 5D's
  `index_design_version_task` when needed.
- **Cross-jurisdiction rerank prior.** When multiple jurisdictions
  share a topic, the agent has to rank manually via the prompt.
  A future flag could deterministically prefer the most specific
  jurisdiction at the retriever level.

---

## Operations

### Re-ingesting a document

```bash
# 1. Drop the existing document row (CASCADE wipes chunks).
psql katha -c "DELETE FROM knowledge_documents WHERE id = '<doc-id>';"

# 2. Run the ingester with the new source bytes.
python -c "
import asyncio
from app.corpus import CorpusIngester, extract_pdf
from app.database import async_session_factory

async def main():
    doc = extract_pdf(
        source_id='nbc-2024',
        title='NBC India',
        payload=open('nbc_2024.pdf', 'rb').read(),
        jurisdiction='nbc_india_2024',
        publisher='BIS',
        edition='2024',
        effective_from='2024-04-01',
    )
    async with async_session_factory() as db:
        result = await CorpusIngester().ingest(db, document=doc)
        await db.commit()
    print(result)

asyncio.run(main())
"
```

### Switching embedders

If you change `openai_embedding_model` to a different dim:

1. Update `app/models/orm.py` — `Vector(1536)` → new dim.
2. New migration to ALTER the column (data is lost — embeddings
   aren't portable across models).
3. Re-ingest the entire corpus.

### Inspecting a chunk

```sql
SELECT id, document_id, page, section, length(content) AS content_len
FROM knowledge_chunks
WHERE jurisdiction = 'nbc_india_2016'
  AND content_tsv @@ plainto_tsquery('english', 'corridor hospital')
ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('english', 'corridor hospital')) DESC
LIMIT 5;
```
