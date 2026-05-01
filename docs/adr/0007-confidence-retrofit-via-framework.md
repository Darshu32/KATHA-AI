# ADR 0007 — Retrofit confidence + provenance at the framework layer, not per-tool

Status: Accepted
Date: 2026-05-01
Stage: 11 (reasoning transparency)

## Context

Stage 11 required every agent tool's result to carry a confidence
block (score + kind + factors) and a provenance banner (catalog
versions + tool stamp + request_id). At the time of decision, 78
tools were already in production.

The user's explicit ask: **"push for full retrofit across all 78
tools."**

## Decision

Apply the retrofit **once, in the framework**, by mutating
`call_tool` (the dispatcher) to wrap every successful result with
the new fields. Zero per-tool file changes for the 78 prior tools.

Three resolution sources, in order:

1. **Runtime override** — `ctx.state["confidence_override"]` set
   by the tool just before returning. RAG tools stamp their
   actual top-k similarity here. LLM tools that self-report
   confidence stamp it here.
2. **Decorator declaration** — `@tool(confidence_kind="...")`.
   Tools authored Stage-11+ are encouraged to declare here.
3. **Curated map** — `_DEFAULT_KIND_BY_TOOL` in
   `app/agents/confidence.py`. The Stage 11 retrofit shipped this
   map covering the 78 prior tools by name.

Provenance is always built fresh from
`app.provenance.build_banner()` — no per-tool participation needed.

## Alternatives considered

- **Mutate every tool's output Pydantic model** to include
  `confidence` + `provenance` fields — rejected. 78 model
  changes; every tool's tests break; downstream consumers (chat
  serialiser, audit row writer) would need updating. Massive
  surface area for a feature that's purely additive at the
  envelope level.
- **Wrapper class at the call site** — rejected. Every consumer
  of a tool result would need to unwrap. The `call_tool` dispatcher
  is already the chokepoint; one change there propagates.
- **Decorator-only declaration (no map)** — rejected. Would
  require touching all 78 tool files to add `confidence_kind=...`.
  The map gives us "good defaults" without 78 file edits.
- **Skip confidence on the 78 prior tools, only new ones get it**
  — rejected. The user explicitly asked for full retrofit. Half-
  retrofit creates a "why does this tool show 92% but that one
  shows nothing" UX problem.

## Consequences

- **Zero per-tool churn** for the Stage 11 retrofit. The 78
  existing tool modules were untouched.
- **The curated map is the new source of "what's a tool's
  inherent confidence"** — when adding a tool, either declare on
  the decorator or update the map. The Stage 11 unit test asserts
  every registered tool resolves a non-`unknown` kind.
- **Runtime override is the escape hatch** — when a tool's
  confidence depends on the *call*, not its *kind*, the tool sets
  `ctx.state["confidence_override"]` and the framework picks it
  up. Used by RAG and LLM-self-report tools.
- **Tests can verify the framework retrofit once** — one
  integration test confirms every successful `call_tool` result
  has the new fields. We don't write 78 per-tool tests.
- **Future tool consumers (UI, integrations) get free transparency**
  — every result carries the data; rendering "92% confidence; 3
  reasons" is a UI concern, not a backend rebuild.

This pattern is reusable. If Stage 12+ needs another envelope
field (e.g. `cost_estimate_inr` per call), the same retrofit
approach works — change `call_tool`, update the map, done.

Re-evaluate at: when a new envelope field needs *per-tool*
authoring (i.e. not derivable from a static map). At that point,
the map → decorator migration becomes worth doing.
