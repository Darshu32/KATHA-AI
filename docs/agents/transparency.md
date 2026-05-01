# Stage 11 — Reasoning Transparency

> **Goal:** Make the agent's thinking visible and challengeable.
> Architects must be able to interrogate any number, any choice,
> any artefact — and trust the answer enough to ship it to a client.

## The trust contract

Every output the agent produces — every cost number, every theme
suggestion, every dimension call — comes with three things:

1. **Confidence** — a number between 0 and 1, plus the *kind* of
   confidence (deterministic math, vetted catalog read, RAG top-k,
   LLM with validator pass, LLM unvalidated, …) and the factors that
   contributed.
2. **Provenance** — which catalog versions, which tool, which
   request_id produced this artefact. Pin the artefact to its
   inputs forever.
3. **Recourse** — when the agent makes a meaningful choice it
   records a :class:`DesignDecision` with reasoning steps + sources
   + alternatives considered. The architect can challenge any
   decision; the agent re-reasons or accepts the override.

This document is the contract. UI and integrations consume the
shapes described here.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AGENT TOOL CALL                           │
│  spec.fn(ctx, input) → BaseModel                                 │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  app.agents.tool.call_tool — Stage 11 retrofit                   │
│  Wraps the tool's output with two new fields:                    │
│    "confidence": {score, kind, factors}                          │
│    "provenance": {schema_version, catalog_versions, …}           │
└──────────────────────┬───────────────────────────────────────────┘
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
   confidence       provenance      DesignDecision
   resolver         banner          (when the choice
   (kinds map)      builder         is meaningful)
```

The retrofit lives in **one place** (`app/agents/tool.py:call_tool`)
so all 81 tools surface confidence + provenance without each tool
file being edited. Tools authored after Stage 11 are encouraged to
declare `confidence_kind` on their `@tool` decorator; the framework
falls back to a curated map (`app/agents/confidence.py`) for the
prior 78.

## The result envelope

Every successful `call_tool` result is shaped:

```jsonc
{
  "ok": true,
  "output": { /* tool's Pydantic output, unchanged */ },
  "elapsed_ms": 12.34,

  "confidence": {
    "score": 0.92,                  // 0..1, or null when "unknown"
    "kind": "llm_validated",        // see KINDS table below
    "factors": ["nbc_compliance_verified", "all_inputs_in_catalogue"]
  },

  "provenance": {
    "schema_version": "11.0.0",
    "generated_at": "2026-05-01T12:34:56.789+00:00",
    "tooling_generation": "1.0.0",
    "catalog_versions": {
      "haptic_catalog": "2026.05.01",
      "haptic_schema": "9.0.0",
      "themes": "1",
      "pricing": "1",
      "knowledge_corpus": "1"
    },
    "tool": "estimate_project_cost",
    "tool_invocation_kind": "agent_call",
    "request_id": "req-abc123"
  }
}
```

Errors keep the existing envelope shape — confidence/provenance
only attach to successful calls.

## Confidence — the nine kinds

| Kind | Default score | When to use |
|---|---|---|
| `deterministic` | 1.00 | Math + lookup. Same inputs → same output, every time. Cost engine, sensitivity re-walk, dimension validators. |
| `static_catalog` | 1.00 | Read from a vetted seed catalog. Theme rule packs, NBC code lookups, ergonomic ranges. |
| `rag` | 0.85† | Top-k similarity retrieval. **Override at runtime** with the actual top-k score. |
| `llm_validated` | 0.90 | LLM output that passes a deterministic re-walk validator (cost engine specs, drawings, sensitivity). |
| `llm_self_report` | null | The LLM declares its own confidence. Set the score from the LLM's response via runtime override. |
| `llm_unvalidated` | 0.65 | LLM output with no validator pass. Use for opinion-driven outputs (diagrams, advisory recs). |
| `heuristic` | 0.75 | Rule-based + parametric, no validator. |
| `io_export` | 1.00 | Deterministic byte production (file exporters). |
| `unknown` | null | Last resort — caller can't claim a number. |

†RAG default is conservative; tools should override at runtime with
the actual top similarity score so the architect sees real numbers.

### Resolution order

When the framework computes the confidence block, it walks this
chain (first match wins):

1. **Runtime override** — `ctx.state["confidence_override"]`
   set by the tool before returning. Use this for tools whose
   confidence depends on the actual run (RAG, LLM self-report).
2. **Decorator declaration** — `@tool(confidence_kind="...")`.
   The static answer for tools with predictable confidence kind.
3. **Curated map** — `app/agents/confidence.py:_DEFAULT_KIND_BY_TOOL`.
   The Stage 11 retrofit for the 78 prior tools.
4. **Unknown** — last-resort fallback. `score=null`.

### Example — runtime override (RAG)

```python
@tool(name="search_project_memory", ...)
async def search_project_memory(ctx, input):
    hits = await retriever.search(...)
    if hits:
        ctx.state["confidence_override"] = {
            "score": hits[0].score,           # actual top similarity
            "kind": "rag",
            "factors": [f"top_k={hits[0].score:.2f}",
                        f"n_results={len(hits)}"],
        }
    return SearchOutput(hits=hits)
```

The framework picks up `confidence_override` after the tool returns
and wraps it into the envelope. The tool's Pydantic output is
unchanged.

## Provenance — the source-of-truth banner

Every output stamps these fields:

| Field | Source | What it tells you |
|---|---|---|
| `schema_version` | `PROVENANCE_SCHEMA_VERSION` | Banner JSON shape version (semver). Bump on breaking changes. |
| `generated_at` | `datetime.now(UTC)` | Wall clock at the moment of generation. |
| `tooling_generation` | `TOOLING_GENERATION` | Bumps when the agent toolset signature changes (new stages, breaking reshapes). |
| `catalog_versions.haptic_catalog` | `app.haptic.HAPTIC_CATALOG_VERSION` | Stage 9 catalog version. |
| `catalog_versions.haptic_schema` | `app.haptic.HAPTIC_SCHEMA_VERSION` | Stage 9 export-payload schema version. |
| `catalog_versions.themes` | `THEME_CATALOG_GENERATION` | Theme rule pack generation. |
| `catalog_versions.pricing` | `PRICING_CATALOG_GENERATION` | Pricing snapshot generation. |
| `catalog_versions.knowledge_corpus` | `CORPUS_GENERATION` | Stage 6 RAG corpus generation. |
| `tool` | from `call_tool` | Which tool ran. |
| `tool_invocation_kind` | from `call_tool` | `agent_call` \| `scheduled_task` \| `http_route` \| `service_internal`. |
| `request_id` | from `ctx.request_id` | Joins to the AuditEvent row for the same call. |

When a banner is built outside of `call_tool` (e.g. a service
composing a spec bundle), call `app.provenance.build_banner(...)`
directly and stamp `tool` / `tool_invocation_kind` / `request_id`
manually.

## DesignDecision — the reasoning artefact

`design_decisions` rows now carry four Stage 11 fields on top of
the Stage 8 columns:

| Column | Type | Notes |
|---|---|---|
| `reasoning_steps` | JSONB | Ordered list of `{step, observation, conclusion}` dicts. |
| `confidence_score` | Float (nullable) | 0..1. Null for legacy Stage 8 rows. |
| `confidence_factors` | JSONB | List of strings, e.g. `["nbc_compliance_verified", "cost_within_budget"]`. |
| `provenance` | JSONB | Full banner snapshot at decision time. |

The agent records reasoning + confidence via the existing
`record_design_decision` tool — Stage 11 added optional input fields
that don't break Stage 8 callers.

## Challenges — three-state resolution

The architect can challenge any recorded decision. Two surfaces:

- **Agent tool** — `challenge_design_decision`. Lets the agent
  file a challenge in-conversation when the user pushes back.
- **HTTP route** — `POST /projects/{project_id}/decisions/{decision_id}/challenge`.
  Lets the UI file a challenge directly when the user clicks
  "challenge this decision."

Resolution states:

| Resolution | Meaning | Required side-effect |
|---|---|---|
| `pending` | Filed, not yet resolved | None — agent picks it up later |
| `rejected_challenge` | Agent re-reasoned and stands by the decision | `response_reasoning` populated |
| `decision_revised` | Agent agrees the challenge has merit; a new decision supersedes the original | `new_decision_id` links the successor |
| `accepted_override` | User overrides without re-reasoning | optional `new_decision_id` |

A re-challenge after a resolution **creates a new row** — the
ledger is append-only. `explain_decision` returns the full chain
of challenges so the audit trail stays intact.

## Alternatives explorer — the rejection ledger

`compare_alternatives` is the generic "given N options + M criteria,
pick a winner" tool. Its critical guarantee:

> **Every loser is recorded with a reason.** Silent rejections are
> rejected at validation time.

When `auto_record_decision=True` (default), a fresh
`DesignDecision` is written with:

- `title` = the decision question
- `summary` = the winner's name + composite score
- `rejected_alternatives` = full list of every loser, each with
  `option`, `composite_score`, `reason_rejected`, `properties`,
  `per_criterion` scores
- `reasoning_steps` = one step per option (winner + losers), each
  step's conclusion either `"winner"` or the rejection reason

The architect can later call `explain_decision` and see exactly
which alternatives were considered and why each lost.

## HTTP surface

```
GET  /api/v1/projects/{project_id}/decisions
GET  /api/v1/projects/{project_id}/decisions/{decision_id}
POST /api/v1/projects/{project_id}/decisions/{decision_id}/challenge
```

All three are owner-guarded. Cross-owner access returns 404 with the
same shape as 'not found' — existence isn't leaked. UI/integration
auth via the standard `get_current_user` dependency.

### Example — list decisions

```bash
GET /api/v1/projects/PROJ_123/decisions?category=material&limit=20
```

```json
{
  "project_id": "PROJ_123",
  "total": 47,
  "decisions": [
    {
      "id": "DEC_abc",
      "title": "Picked walnut for kitchen island",
      "category": "material",
      "confidence_score": 0.92,
      "confidence_factors": ["theme_pack_match", "cost_within_budget"],
      "reasoning_steps": [
        {"step": "check_theme_palette",
         "observation": "MCM primary palette = [walnut, teak]",
         "conclusion": "Walnut is in the BRD-anchored palette"},
        ...
      ],
      "rejected_alternatives": [
        {"option": "oak", "reason_rejected": "Cooler tone"}
      ],
      "sources": ["theme_pack:mid_century_modern"],
      "provenance": {
        "tool": "record_design_decision",
        "catalog_versions": {...}
      },
      ...
    },
    ...
  ]
}
```

### Example — file a challenge

```bash
POST /api/v1/projects/PROJ_123/decisions/DEC_abc/challenge
Content-Type: application/json

{
  "challenge_text": "Walnut blows the budget by 8% — re-evaluate.",
  "resolution": "decision_revised",
  "response_reasoning": (
    "Verified — recosted with oak, saves ₹12,000. New decision DEC_xyz."
  ),
  "new_decision_id": "DEC_xyz"
}
```

→ `201 Created` with the resolved challenge row.

## What architects see (the BRD ask)

> *"Architect can hover any number/decision and see: 'I picked oak
> because… (3 reasons, 2 alternatives, 1 NBC citation, 92%
> confidence).'"*

The data this requires is in place. UI rendering is a separate
phase — when it lands, the tooltip composer reads:

| BRD asks for | Data source |
|---|---|
| "I picked oak" | `decision.title` + `decision.summary` |
| "3 reasons" | `decision.reasoning_steps` |
| "2 alternatives" | `decision.rejected_alternatives` |
| "1 NBC citation" | `decision.sources` |
| "92% confidence" | `decision.confidence_score` |

## Test surface

| Test | What it locks |
|---|---|
| `tests/unit/test_stage11_transparency.py` | Banner shape + version stamps; KINDS enum stable; every curated tool maps to a real kind; runtime override beats declaration; declaration beats curated map; clamping at unit interval; tool registry shape; **all 78 prior tools resolve a real kind** |
| `tests/integration/test_stage11_transparency.py` | Framework retrofit — every `call_tool` result has `confidence` + `provenance`; runtime override picked up; `record_design_decision` round-trips reasoning + confidence + provenance; `explain_decision` returns full record + challenge chain; cross-project guard; all 3 challenge resolutions; pending state; `compare_alternatives` auto-records with rejection ledger; rejection-reason validation |

## Deferred to later stages

These items showed up during Stage 11 design but didn't ship:

- **Per-tool runtime confidence overrides** for the 78 retrofitted
  tools. The framework supports it; tools opt in as they're
  naturally edited (RAG retrievers, LLM self-reporters first).
- **Provenance stamping inside service-layer outputs** (spec
  bundle, BOQ rows). The banner builder is centralised so any
  service can call `build_banner()` directly; rolling it into the
  spec bundle is a Stage 11B polish task.
- **UI tooltip composer** — render a "92% confidence; 3 reasons"
  hover from the JSON. UI phase.
- **Confidence-based gating** — block downstream tools when an
  upstream's confidence is below threshold. Currently advisory
  only.

---

## Sign-off

> Every numeric output, every meaningful choice, every artefact
> KATHA-AI produces in Stage 11 onwards carries confidence,
> provenance, and a recourse path. The architect can interrogate
> any decision and either accept the agent's reasoning or override
> with full audit trail.
