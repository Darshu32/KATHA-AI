# Stage 5B — Project Memory (RAG)

> **Audience:** future-you debugging a recall result, tuning the
> chunker, switching embedders, or wiring auto-indexing into the
> generation pipeline. Read after `docs/agents/runtime.md`.

---

## What Stage 5B added

The agent can now **search project artefacts by content** instead of
by id. When the architect says "what did we say about kitchen
materials?", the agent queries semantic memory and gets back the
relevant chunks across design versions, spec bundles, cost runs,
drawings, and diagrams.

```
                ┌─────────────────────────────────────────────────────┐
                │                  agent loop                         │
                └─┬───────────────────────────────────────────────────┘
                  │
       search_project_memory(query)         index_project_artefact(kind, body)
                  │                                       │
                  ▼                                       ▼
           ProjectMemoryRetriever              ProjectMemoryIndexer
                  │                                       │
                  │   embed(query)                        │   chunk(body)
                  │   ────────────►   Embedder            │   ─────────►   Chunker
                  │   ◄───────────── (vec[1536])          │
                  ▼                                       │   embed(chunks)
        ProjectMemoryRepository.search                    │   ───────────►   Embedder
                  │                                       │   ◄────────── (vecs[1536])
                  │   pgvector cosine                     ▼
                  │   ────────────►   Postgres           Repository.delete + insert
                  │   ◄───────────── (chunks, dist)       │
                  ▼                                       ▼
           SearchHit[]                            IndexResult
```

---

## Module map

```
backend/app/
├── memory/                              NEW package
│   ├── __init__.py                      Public API (Embedder, indexer, retriever)
│   ├── embeddings.py                    OpenAI + Stub embedders
│   ├── chunker.py                       Per-source-type text chunkers
│   ├── indexer.py                       Write side — idempotent
│   └── retriever.py                     Read side — top-K cosine search
├── repositories/project_memory/         NEW
│   ├── __init__.py
│   └── memory_repo.py                   ProjectMemoryRepository
├── agents/tools/memory.py               NEW — 3 agent tools
└── models/orm.py                        + ProjectMemoryChunk class

backend/alembic/versions/0016_*.py        NEW — pgvector + table + IVFFlat
```

---

## Schema

`project_memory_chunks`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `project_id` | FK projects (CASCADE) | All chunks for a project go away when the project does |
| `owner_id` | FK users (CASCADE) | Carried explicitly so search can cheap-filter without joining |
| `source_type` | varchar(64) | `design_version` / `spec_bundle` / `cost_engine` / `plan_view` / etc. |
| `source_id` | varchar(64) | Stable id from the producing tool — version_id, snapshot_id, etc. |
| `source_version` | varchar(64) | Optional: `v3`, `v77`, … |
| `chunk_index` | int | 0-based |
| `total_chunks` | int | How many chunks this source produced |
| `content` | text | The exact text we embedded |
| `token_estimate` | int | Heuristic — 4 chars ≈ 1 token |
| `embedding` | `vector(1536)` | OpenAI `text-embedding-3-small` |
| `metadata` | jsonb | Display extras (title, theme, version int, …) |

Indexes:
- `(project_id, source_type, source_id, source_version)` — fast lookup for re-index delete
- `(project_id, owner_id)` — scoped search filter
- `(project_id)` — list all of a project
- IVFFlat on `embedding USING vector_cosine_ops WITH (lists=100)` — the actual ANN index

---

## Source types we index

| `source_type` | Source | Chunker function |
|---|---|---|
| `design_version` | `DesignGraphVersion.graph_data` | `chunk_design_version` |
| `spec_bundle` | Stage 4D bundle (material+manufacturing+mep+cost) | `chunk_spec_bundle` |
| `cost_engine` | Stage 2 cost engine breakdown | `chunk_cost_engine` |
| `plan_view` / `elevation_view` / `section_view` / `detail_sheet` / `isometric_view` | Stage 4E drawings (the structured spec, not the SVG) | `chunk_drawing_or_diagram` |
| `concept_transparency` / `form_development` / `volumetric_hierarchy` / `volumetric_block` / `design_process` / `solid_void` / `spatial_organism` / `hierarchy` | Stage 4F diagrams | `chunk_drawing_or_diagram` |

The chunker turns each source into prose — labelled fields the
embedder can lock onto (`Theme: scandinavian`, `Materials: walnut, brass`).
We deliberately **don't index the SVG** for drawings/diagrams — only
the LLM-authored spec.

---

## Embedders

Two implementations of the `Embedder` ABC:

| Class | Use | Notes |
|---|---|---|
| `OpenAIEmbedder` | Production | `text-embedding-3-small`, 1536 dims, 30 s timeout, batch up to 2048 inputs per call |
| `StubEmbedder` | Tests + offline dev | Hashes input → deterministic 1536-dim L2-normalised vector. Same input ⇒ same vector, but no semantic relationship between different inputs |

`get_embedder()` returns OpenAI when `OPENAI_API_KEY` is set, otherwise
falls back to `StubEmbedder` and logs a warning — so the system runs
without an OpenAI key, just without semantic similarity.

Tests inject `StubEmbedder` directly into `ProjectMemoryIndexer` /
`ProjectMemoryRetriever` so the suite stays hermetic.

---

## Indexing semantics

Every `index_*` call is **delete-then-insert** for the logical key
`(project_id, source_type, source_id, source_version)`. Re-indexing
the same source replaces its chunks rather than duplicating them.

| Method | Source key |
|---|---|
| `index_design_version` | `(project, design_version, version_id, "v{N}")` |
| `index_spec_bundle` | `(project, spec_bundle, version_id, "v{N}")` |
| `index_cost_engine` | `(project, cost_engine, snapshot_id, "")` |
| `index_drawing_or_diagram` | `(project, kind, artefact_id, version)` |

The `IndexResult` returned carries `deleted_count` so the caller knows
whether this was a fresh insert or a replace.

### Failure modes

- **Empty content**: `chunk_count=0`, `skipped_reason="no_content"`,
  no rows touched.
- **Embedder fails**: re-raises `EmbeddingError`. Pre-existing chunks
  stay because the delete is in the same transaction — flush
  failure rolls back.
- **DB write fails**: standard SQLAlchemy error bubbles up, transaction
  rolls back.

---

## Search semantics

```python
hits = await ProjectMemoryRetriever().search(
    db,
    project_id="...",
    query="kitchen lighting circuits",
    owner_id=user.id,         # always pass — defence in depth
    source_type="mep_spec",   # optional — None = search everything
    top_k=5,                  # 1..50 (clamped at repo)
)
```

Each `SearchHit` has:
- `content` — the exact text we embedded
- `score` ∈ [-1, 1]  (cosine similarity; ≥ 0.7 = confident, < 0.3 = weak)
- `distance` ∈ [0, 2] (raw cosine distance from pgvector)
- `source_type`, `source_id`, `source_version`, `chunk_index`, `total_chunks`
- `extra` — display metadata (title, theme, project_name, …)

The repo uses pgvector's `<=>` operator (cosine distance) under
`vector_cosine_ops` — that's what the IVFFlat index supports. Other
distance metrics need a different index.

---

## Agent tools (Stage 5B adds 3)

| Tool | Type | Audit |
|---|---|---|
| `search_project_memory` | Read | none |
| `index_project_artefact` | Write | `project_memory` |
| `project_memory_stats` | Read | none |

Both `search` and `stats` are read-only (no audit), so they're eligible
for the Stage-5 parallel dispatcher. `index` writes audit events.

All three guard `ctx.project_id` and `ctx.actor_id` — refusing to run
without a project + an authenticated user.

### Typical agent flows

**Indexing a fresh design version:**
```
1. user: "Design me a modern kitchen"
2. agent → generate_initial_design     → version 1 saved
3. agent → index_project_artefact      kind="design_version"
                                        source_id=<version_id>
                                        source_version="v1"
                                        body=<full_graph_data>
4. agent: "Done — version 1 saved and indexed."
```

**Recalling earlier work:**
```
1. user: "what materials did we pick for the island?"
2. agent → search_project_memory       query="island materials"
                                        source_type="design_version"
3. agent receives hit with content showing walnut + brass.
4. agent: "We picked walnut for the island, brass for the hardware."
```

---

## Stage 5C — Auto-indexing in the pipeline

The Stage 4G write tools (`generate_initial_design`, `apply_theme`,
`edit_design_object`) all auto-index the freshly-saved design version
into project memory after the pipeline returns. The agent no longer
has to call `index_project_artefact` manually for every generation.

**Best-effort semantics.** If indexing fails for any reason — embedder
down, OpenAI rate-limited, DB error during chunk insert — the parent
generation **still succeeds**. The failure surfaces on
`GenerationOutput`:

```python
{
  "indexed": False,
  "index_chunk_count": 0,
  "index_skipped_reason": "error",      # or "no_project_id" / "no_owner_id" / "no_content"
  ...                                   # all the usual generation fields
}
```

The implementation is a thin wrapper in
`app/agents/auto_index.py` that:

1. Short-circuits with the matching `skipped_reason` if scope is
   missing (`no_project_id` / `no_owner_id` / `no_version_id`) —
   no DB call attempted.
2. Catches every exception from `ProjectMemoryIndexer.index_design_version`
   and returns `skipped_reason="error"` with the exception message.
3. Treats a 0-chunk result (empty graph) as `skipped_reason="no_content"`
   — explicit skip, not an error.

**Scope: design versions only.** Specs / drawings / diagrams / cost
runs stay agent-driven via `index_project_artefact`. Their bodies
only exist in the agent's reply (no DB row of their own), so an
explicit indexing call is the right surface.

**Cost model.** Auto-indexing adds one embedding round-trip per
generation (~500 ms — 2 s with OpenAI; near-instant with the stub).
We accept this latency for now; Stage 5D may move indexing to Celery.

---

## Stage 5D — Async indexing + eviction

Stage 5D adds two complementary capabilities on top of Stage 5C's
inline auto-indexing:

### Async indexing (off by default)

The `async_indexing_enabled` setting (default `False`) flips the
auto-indexer into Celery dispatch mode. The pipeline tools then return
immediately with `index_skipped_reason="queued"` and a Celery
`index_task_id`; a worker writes chunks behind the scenes.

| Mode | Latency added to generation | Failure mode |
|---|---|---|
| Inline (5C, default) | +500 ms – 2 s | `indexed=False`, `skipped_reason="error"` |
| Async (5D, opt-in) | ~0 ms | `skipped_reason="queued"` (success), `"dispatch_failed"` (broker outage) |

The async path uses a new Celery task at
`app.workers.memory_tasks.index_design_version_task` routed to the
`ingestion` queue. The task:

- Opens its own DB session — separate transaction from the
  request that dispatched it.
- Receives the full `graph_data` payload directly so it doesn't
  need to re-read the version row (avoids "task picked up before
  parent commit" races).
- Auto-retries 3× with exponential backoff on any exception.
- Persistent failures are logged + dropped — the user-facing
  generation has long since succeeded.

A 1-second `countdown` on dispatch gives the parent transaction time
to commit before the worker picks up the job. Tests use Celery's
eager mode (or call the task body directly) to skip the broker.

### Eviction — `prune_project_memory`

A new write tool that drops `design_version` chunks for older
versions, keeping the latest N. Useful for projects that accumulate
dozens of design versions:

```python
{
  "keep_latest_versions": 10  // 1..200
}
→ {"project_id": "...", "keep_latest_versions": 10,
   "removed_count": 17, "chunks_remaining": 23}
```

Pruning is **scoped to `design_version` only** — spec, cost,
drawing, and diagram chunks are left alone. Their `source_version`
semantics differ (they're agent-driven, not auto-versioned), so a
generic prune would need a per-source-type retention policy.
Out-of-scope for 5D.

`keep_latest <= 0` is a no-op — we never truncate the entire project
through this tool. The output shape lets the agent confirm the prune
was bounded.

### `index_task_id` field on `GenerationOutput`

Stage 5D extends the pipeline tools' output with an `index_task_id`
string when async dispatch succeeds. Clients can poll Celery's
result backend (Redis db 2) to confirm the worker finished. Inline
mode leaves it `null`.

| Mode | `indexed` | `skipped_reason` | `index_task_id` | `chunk_count` |
|---|---|---|---|---|
| Inline success | `true` | `null` | `null` | N |
| Inline empty graph | `false` | `"no_content"` | `null` | 0 |
| Inline error | `false` | `"error"` | `null` | 0 |
| Async dispatched | `false` | `"queued"` | `"<uuid>"` | 0 |
| Async broker down | `false` | `"dispatch_failed"` | `null` | 0 |

---

## What's *not* here yet

- **Cross-project search.** `search_project_memory` is scoped to one
  `project_id`. Cross-project recall ("any kitchen I've designed")
  needs a different tool with extra owner-scoping.
- **Per-source-type retention.** `prune_project_memory` only handles
  `design_version`. Spec / cost / drawing / diagram chunks live
  forever until manually re-indexed. Adding retention for those
  needs deciding what "old" means per kind.
- **Auto-prune on archival.** Archiving a project (Stage 0 model
  status `archived`) doesn't currently trigger a memory wipe.
- **Tokeniser fidelity.** The chunker uses a 4-chars-per-token
  heuristic rather than `tiktoken` — fine at the scales we work with,
  but worth swapping in once the chunker becomes a hot path.

---

## Test surface

- `tests/unit/test_stage5b_memory.py`
  - `StubEmbedder` determinism + L2-normalisation
  - `chunk_text` boundaries (empty / small / above target / above max)
  - Per-source-type chunker output anchors
  - Tool registry shape (search read-only, index has audit, stats no required input)
- `tests/integration/test_stage5b_memory.py`
  - Index → search round-trip against real Postgres + pgvector
  - Re-indexing replaces prior chunks
  - `source_type` filter excludes other kinds
  - `owner_id` filter isolates users
  - Per-source-type indexers (`design_version`, `spec_bundle`,
    `cost_engine`, drawing) write rows with the right metadata
  - End-to-end via `call_tool` for `index_project_artefact` →
    `project_memory_stats` → `search_project_memory`
- `tests/unit/test_stage5c_auto_index.py`
  - `auto_index_design_version` happy path returns `indexed=True`
  - Missing scope (`project_id` / `owner_id` / `version_id`) short-circuits
    with the matching `skipped_reason` — no indexer call
  - Empty source → `skipped_reason="no_content"`, no `error`
  - Indexer raising `RuntimeError` / `ValueError` is caught and
    surfaces as `skipped_reason="error"` with the message
- `tests/integration/test_stage5c_auto_index.py`
  - Each of `generate_initial_design` / `apply_theme` /
    `edit_design_object` writes real chunks
  - Auto-indexed content is searchable via `search_project_memory`
    in the same transaction
  - Indexer crash leaves the parent generation `ok=True` with
    `indexed=False`
  - `actor_id=None` short-circuits with `no_owner_id`
- `tests/unit/test_stage5d_async_index.py`
  - `AutoIndexResult.from_queued` shape (with / without task id)
  - `async_mode=True/False/None` mode-selection logic
  - Settings flag flip flips the default mode
  - Dispatcher returning `None` → `dispatch_failed`
  - `prune_project_memory` registry shape + bounds
  - `GenerationOutput` carries `index_task_id`
- `tests/integration/test_stage5d_async_and_prune.py`
  - Async path through `generate_initial_design` returns
    `index_skipped_reason="queued"` + populated `index_task_id`,
    no chunks written inline
  - Direct execution of `index_design_version_task` body writes
    real chunks (the eager-Celery path)
  - `prune_old_design_versions` keeps the latest N, drops older
  - Pruning leaves spec / cost / drawing chunks untouched
  - `keep_latest=0` is a no-op (defence against truncation)
  - `prune_project_memory` tool drives all of the above through
    `call_tool`
