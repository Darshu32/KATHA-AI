# ADR 0001 — pgvector over Pinecone for project memory

Status: Accepted
Date: 2026-04-30
Stage: 5B (project memory RAG)

## Context

Stage 5B introduced project-scoped semantic recall — the agent
needs to find past design discussions, spec excerpts, and
estimates relevant to the current chat turn. Two storage paths
were on the table:

1. **pgvector** — extension on the existing Postgres instance,
   one ORM table (`project_memory_chunks`), one IVFFlat index.
2. **Pinecone / Weaviate / Qdrant** — managed vector DB,
   separate service, separate auth.

## Decision

Use **pgvector** in the existing Postgres database. One vector
column with cosine-distance IVFFlat index. Embeddings live in the
same row as their source metadata.

## Alternatives considered

- **Pinecone** — rejected. Adds an external service to the boot
  dependency list; another set of credentials to manage; vendor
  lock-in for a workload that fits comfortably in Postgres at the
  Phase-1 scale (< 10M chunks projected). Cost ramps quickly past
  the free tier. Doesn't compose with the Stage 8 owner-guard
  pattern — every retrieval would need a second filter pass.
- **Weaviate / Qdrant self-hosted** — rejected. Same operational
  overhead (separate process, separate backups) without the
  managed-service convenience. We already operate Postgres; one
  more table is free.
- **In-process FAISS** — rejected. Fine for prototypes; can't
  share state across multiple API processes. We need persistent,
  multi-reader storage from day 1.

## Consequences

- **Single source of truth** — the design graph + memory chunks +
  audit log all live in one DB. Backups capture everything in one
  pg_dump. Cross-table joins (e.g. "find chunks indexed by tools
  the user invoked") are trivial.
- **Owner-guard composable** — `WHERE project_id = X` + vector
  similarity in one query. Stage 11 explain endpoints depend on
  this.
- **Index choice locked** — IVFFlat needs `lists` tuning as data
  grows. At ~1M chunks consider HNSW or partition by project_id.
- **No native re-ranking** — Pinecone has hybrid search built-in;
  we built our own (Stage 6 — 0.7 vec + 0.3 BM25). Slightly more
  code, but stays in our stack.
- **Vendor independence** — if pgvector ever becomes a bottleneck,
  the migration to a real vector DB is one indexer rewrite + one
  retriever rewrite. We've kept the read API behind a class
  (`ProjectMemoryRetriever`), so the swap is contained.

Re-evaluate at: 10M chunks per project, OR when query P95 > 200ms
on the IVFFlat index.
