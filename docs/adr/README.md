# Architecture Decision Records

> One short doc per major architectural choice. The point is
> recoverability — when you (or future-you) wonder "why did we
> do it this way," the answer lives here, not in someone's head.

## Format

Each ADR is a single Markdown file under `docs/adr/`, numbered
sequentially. Template:

```
# ADR NNNN — <one-line decision>

Status: Accepted | Superseded by ADR-XXXX | Deprecated
Date: 2026-MM-DD
Stage: <which build stage made this call>

## Context
What forced the decision? What constraints / data informed it?

## Decision
What was chosen, in one or two sentences.

## Alternatives considered
Each alternative as a sub-bullet with the *reason rejected*.

## Consequences
What downstream choices does this lock in? What's now harder?
```

ADRs are append-only. To revise a decision, write a new ADR that
*supersedes* the old one (and update the old one's status).

## Index

| # | Title | Status | Stage |
|---|---|---|---|
| [0001](./0001-pgvector-over-pinecone.md) | pgvector over Pinecone for project memory | Accepted | 5B |
| [0002](./0002-anthropic-plus-openai.md) | Anthropic Claude as primary, OpenAI for embeddings + fallback | Accepted | 2 |
| [0003](./0003-pure-python-extractors.md) | Pure-Python extractors for nightly profile builds (no LLM) | Accepted | 8 |
| [0004](./0004-tool-framework-pattern.md) | One-decorator tool framework with Pydantic I/O + audit + confidence | Accepted | 2 / 11 |
| [0005](./0005-ifc-not-rvt.md) | IFC export instead of native Revit (.rvt) | Accepted | 10 |
| [0006](./0006-stub-provider-pattern.md) | Stub-provider pattern for external integrations | Accepted | 5B / 7 / 12 |
| [0007](./0007-confidence-retrofit-via-framework.md) | Retrofit confidence + provenance at the framework layer, not per-tool | Accepted | 11 |
