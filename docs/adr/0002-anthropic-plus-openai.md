# ADR 0002 — Anthropic Claude as primary agent runtime, OpenAI for embeddings + fallback

Status: Accepted
Date: 2026-04-30
Stage: 2 (agent runtime)

## Context

Two LLM provider decisions had to be made up front:

1. **Agent runtime** — which model drives the chat / tool-using
   agent loop?
2. **Embeddings** — which model produces the vectors for
   project memory + knowledge corpus RAG?

These decisions are sticky. The agent's system prompt + tool
schemas are calibrated to one provider's tool-use API; embeddings
written by one model can't be searched against vectors from
another.

## Decision

- **Anthropic Claude (`claude-sonnet-4-5`)** as the primary agent
  runtime.
- **OpenAI** for:
    - **Embeddings** (`text-embedding-3-small`) for all RAG indexing.
    - **Fallback / non-agent LLM calls** (specs, sensitivity
      narrative, drawings authoring) where structured JSON output
      is the dominant requirement.

## Alternatives considered

- **OpenAI for everything** — rejected. Claude's tool-use is
  better suited to long-horizon agent loops with many tools; the
  Stage 2 framework was designed against Claude's tool-use shape.
  OpenAI's function-calling works but the developer ergonomics
  for nested / streaming tool use trail.
- **Anthropic for everything** — rejected. Anthropic doesn't
  ship embeddings. Switching to Voyage or Cohere for embeddings
  adds a third provider for one workload.
- **Local model (Llama, Mixtral)** — rejected for Phase 1. Self-
  hosted model ops is its own stage. Comes back into scope when
  per-customer data residency requires it.
- **Single-provider lock-in** — rejected. Outage in either
  provider would take down the agent. Dual-provider gives a
  graceful-degradation story.

## Consequences

- **Two API keys** to manage per environment. Documented in
  `docs/operations.md`.
- **Two budget pools** — Claude per-token costs and OpenAI per-
  token costs are separate line items.
- **Stage-4D specs (LLM-validated)** call OpenAI directly because
  they predate the agent loop and need raw JSON-mode output. Future
  refactor could route these through Claude tool-use as well.
- **Embedding model switch is breaking** — changing
  `text-embedding-3-small` to a different model invalidates every
  vector in the DB. The Stage 5B retriever stamps the model name
  on every chunk row so the operator can detect mixed-corpus
  states; a model swap requires a full re-index.
- **Provider abstraction stayed thin** — both LLMs are wrapped in
  thin adapters; the agent loop knows it's talking to Claude. A
  full provider abstraction would be premature complexity.

Re-evaluate at: per-customer data residency requirements; or if
Claude tool-use price changes by > 2× and OpenAI's stays flat.
