# ADR 0003 — Pure-Python extractors for nightly profile builds (no LLM)

Status: Accepted
Date: 2026-05-01
Stage: 8 (memory system)

## Context

Stage 8 introduced `architect_profiles` (per-user style fingerprint)
and `client_profiles` (recurring client-pattern aggregation). Both
are refreshed nightly via Celery beat. The question: should the
nightly pass be LLM-driven (richer, fuzzier) or deterministic
Python (cheaper, identical-input → identical-output)?

## Decision

**Pure-Python extractors.** Functions in
`app/profiles/architect_extractor.py` and `client_extractor.py`
walk the design-graph + decision history, count themes / materials
/ palette / room-dimensions / tool-usage with explicit thresholds,
and emit structured `ArchitectFingerprint` / `ClientPattern`
dataclasses.

No LLM call in the nightly path.

## Alternatives considered

- **LLM-summarised fingerprint** — rejected. Same input → different
  fuzzy output run-to-run. Hard to debug ("why did the agent
  suggest teak?"); hard to predict cost (500 architects × 20
  projects = $50–200/night just to run the cron); hard to commit
  to data residency ("your project data goes to Anthropic every
  night" is a policy nightmare).
- **LLM-derived but cached** — rejected. Caching adds invalidation
  questions (when did the cache last refresh? does it mean the
  fingerprint is stale?). The pure-Python version is the cache —
  it just rebuilds from source data deterministically.
- **Hybrid: counts + LLM polish** — accepted as a future
  possibility, not Stage-8 scope. The dataclass output can be fed
  to an LLM "translate to prose" pass *when the architect asks
  for the prose*, on-demand, not nightly.

## Consequences

- **Idempotent + cheap** — running the cron 5 times in a row is
  free and produces the same row.
- **No external dependency in the nightly path** — Anthropic / OpenAI
  outage doesn't break the profile refresh.
- **Privacy** — no project data leaves Postgres on the nightly
  path. Combined with the `User.learning_enabled` privacy switch,
  the architect's data stays inside their tenant boundary.
- **Recurring-pattern threshold (≥ 2 occurrences)** — encoded
  explicitly in the extractor. A single-project descriptor doesn't
  graduate to "this client always wants…". This is a value
  judgement; documented in `docs/agents/architect_memory.md`.
- **Fuzziness lost** — the LLM would have caught "modern industrial"
  and "industrial-modern" as the same theme; the Python version
  treats them as distinct strings unless the alias map covers
  both. Mitigation: bias future stages toward canonicalising
  theme keys at the point of recording, not at the point of
  reading.

Re-evaluate at: when "translate fingerprint to architect-readable
narrative" becomes a feature request — that's when the LLM polish
pass earns its keep.
