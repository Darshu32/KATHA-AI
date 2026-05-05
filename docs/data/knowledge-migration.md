# Stage 15 — Knowledge Migration (Python literals → DB-backed)

> **Audience:** future-you maintaining the Layer 1B/1C knowledge plumbing,
> and anyone touching `inject_knowledge()` or the spec services.
> Read after `docs/PRODUCT_TRUTH.md` and `docs/BRD_v2_KATHA_AI.md`.

---

## What this stage solves

The BRD v2 non-negotiable principle:

> **No hardcoded knowledge.** Every datum the user sees is dynamic —
> sourced from RAG over authoritative documents, live feeds, or LLM
> synthesis grounded in retrieved sources.

Stage 3E migrated the **data** to the versioned `building_standards` DB
table and shipped async lookups (`app.services.standards.codes_lookup`,
`ergonomics_lookup`, `manufacturing_lookup`, `mep_sizing`).

But the **runtime consumers** — `inject_knowledge()`, the spec
services, the architect-brief LLM grounding — kept reading directly
from `app.knowledge.*` Python modules. So an admin update via
`POST /admin/standards/code/<slug>` would land in the DB but the brief
intake would keep returning the old Python value.

That drift is what Stage 15 closes.

---

## The pattern: DB-first, Python-fallback ("Pattern C")

Every knowledge access becomes:

```python
nbc_min = (
    await codes_lookup.get_code_data(session, slug="minimum_room_dimensions")
    if session is not None else None
) or codes.NBC_INDIA["minimum_room_dimensions"]
```

Three behaviours fall out:

| Caller passes `session`? | DB row exists? | Result |
|---|---|---|
| ✅ yes | ✅ yes | DB value (admin-editable) |
| ✅ yes | ❌ no | Python literal (fresh DB / missing seed) |
| ❌ no | n/a | Python literal (legacy / sync caller / tests) |

Why this matters:
- **Zero breakage during migration.** Tests and any sync callers keep
  working because they pass no session — they get the Python literal.
- **Admin updates take effect immediately.** Once the DB row is updated
  via `/admin/standards/...`, every brief-intake call that has a
  session reads the new value.
- **Fresh DB still works.** A developer cloning the repo with an empty
  DB still gets the Python-literal baseline; they don't need to seed
  before the brief intake can return a sensible bundle.

The function also annotates `_provenance.source` (`"db"` or
`"python_literal"`) inside each block so the Stage 11 transparency
banner can show where each value came from.

---

## What changed in this stage (15a)

| File | Change |
|---|---|
| [`app/services/knowledge_injector.py`](../../backend/app/services/knowledge_injector.py) | `inject_knowledge` now `async`, accepts `session: AsyncSession \| None = None`. `_building_codes` migrated to DB-first (codes / accessibility / ECBC) |
| [`app/routes/brief.py`](../../backend/app/routes/brief.py) | `/brief/knowledge` and `/brief/architect` now `Depends(get_db)` and `await inject_knowledge(..., session=db)` |
| [`app/services/architect_brief_service.py`](../../backend/app/services/architect_brief_service.py) | `generate_architect_brief` accepts optional `session` and passes it through |
| `build_prompt_preamble` | now requires the bundle as a non-optional arg (the implicit re-call would have hidden an async call inside a sync function) |
| [`tests/unit/test_stage15_knowledge_migration.py`](../../backend/tests/unit/test_stage15_knowledge_migration.py) | New — covers async signature, no-session fallback, DB-hit, DB-miss-with-Python-fallback, prompt preamble contract, bundle-shape stability |

The other knowledge blocks in `inject_knowledge` (`_standard_dimensions`,
`_climate_considerations`, `_structural_logic`, `_mep_strategy`,
`_material_availability`, `_suggested_room_program`) remain Python-only
in this stage. Each follows the **same template** for the next push.

---

## Migration template (apply to remaining blocks)

For each `_block_name(...)` function in `knowledge_injector.py`:

1. Add `session: AsyncSession | None` as the first parameter.
2. Make the function `async`.
3. For each Python-literal access (`some_module.SOME_DICT[key]`), replace with:
   ```python
   value = (
       await some_lookup.get_X(session, slug=...)
       if session is not None else None
   ) or some_module.SOME_DICT[key]
   ```
4. Add `_provenance: {"source": "db" if session else "python_literal"}` to the returned dict.
5. Update `inject_knowledge`'s body to `await _block_name(session, ...)`.
6. Add unit tests mirroring the Stage 15 patterns.

---

## Per-block migration plan

| Block | DB lookup module | Status | Stage |
|---|---|---|---|
| `_building_codes` | `codes_lookup.get_code_data` / `get_accessibility` / `get_ecbc_targets` | ✅ Migrated | **15a (this stage)** |
| `_standard_dimensions` | `codes_lookup.get_code_data("minimum_room_dimensions")` for ceiling; clearances dicts (no DB lookup yet — to add) | 🟡 Pending | 15b |
| `_climate_considerations` | `codes_lookup.get_climate_zone` | 🟡 Pending | 15b |
| `_structural_logic` | `codes_lookup.get_live_loads_is875` / `get_dead_loads` / `get_seismic_zones` / `get_span_limits` / `get_foundation_by_soil` | 🟡 Pending | 15b |
| `_mep_strategy` | `mep_sizing.*` (already async, plug in directly) | 🟡 Pending | 15c |
| `_material_availability` | `themes` table + regional materials (no DB lookup yet — to add for `regional_materials`) | 🟡 Pending | 15c |
| `_suggested_room_program` | `space_standards` (no DB lookup yet — to add) | 🟡 Pending | 15c |

When a block has no DB lookup yet (clearances, regional_materials,
space_standards), the migration is two steps:
1. Add the lookup to `app/services/standards/` (mirroring `codes_lookup`).
2. Repoint the block as above.

---

## What this stage does NOT do (yet)

- **No RAG over authoritative source PDFs.** The DB is curated rows,
  not chunked PDFs. Stage 16 (Knowledge corpus expansion) will bring
  the Stage 6 corpus into the picture so values can be sourced from
  ingested NBC / ECBC / IBC PDFs with verbatim chunk citations.
- **No deletion of the Python literal modules.** They remain as the
  fallback. They can only be deleted when:
    1. Every block is DB-backed (Stage 15c).
    2. RAG over PDFs is in place as a higher-priority source (Stage 16).
    3. A migration has seeded ALL the rows the runtime might ask for.
- **Spec services (`material_spec`, `manufacturing_spec`, `mep_spec`)
  are not yet migrated.** Same template applies. Tracked as Stage 15d.

---

## How to verify it's working

1. Start the backend (`uvicorn app.main:app --reload --port 8000`).
2. Run the brief intake with a session active:
   ```bash
   curl -X POST http://localhost:8000/api/v1/brief/knowledge \
     -H "Content-Type: application/json" \
     -d @sample_brief.json
   ```
3. Inspect `response.knowledge.building_codes._provenance` — should read
   `{"source": "db", "fallback_path": "stage-3e DB row → app.knowledge.codes literal"}`.
4. To prove DB-first is real: update an NBC value via the admin
   endpoint, re-call `/brief/knowledge`, confirm the new value flows.
5. To prove fallback works: drop a row from `building_standards`,
   re-call, confirm the Python-literal value still appears (and the
   intake doesn't crash).

The Stage 15 test suite locks all four behaviours.

---

## Stage 16 preview — RAG over PDFs

When ready, the source priority becomes:

```
RAG (PDF chunks) → DB (curated rows) → Python literal → unavailable
```

Same Pattern C, just one more layer at the top. The `_building_codes`
function would call `app.corpus.CorpusRetriever.search(...)` first,
extract structured values via an LLM tool call (Anthropic's structured
output), fall back to DB, fall back to Python.

The Stage 6 corpus + Stage 12 freshness + Stage 11 transparency banner
machinery already exists — Stage 16 is plumbing.
