# Stage 8 — Architect Memory System

> **Audience:** future-you debugging a fingerprint, switching the
> extractor, wiring system-prompt injection, or auditing privacy.
> Read after `docs/agents/memory.md` (per-project memory) and
> `docs/agents/runtime.md` (chat persistence).

---

## What Stage 8 added

Three memory layers that complement the per-project store from
Stage 5B:

| Layer | Stored in | Refreshed by |
|---|---|---|
| **Decisions** (per-project) | `design_decisions` | The agent (via `record_design_decision`) or the architect via the future UI |
| **Architect fingerprint** (per-user) | `architect_profiles` | Nightly Celery task — pure-Python deterministic extractor |
| **Client patterns** (per-client across projects) | `client_profiles` (+ `clients`) | Same nightly task pattern, keyed on client |

Plus 5 agent tools, a privacy switch on `User`, and a
`resume_project_context` composite read for session resumption.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Working context (LLM token window)                                    │
├────────────────────────────────────────────────────────────────────────┤
│  Conversation memory     →  chat_messages           (Stage 5)          │
│  Per-project artefacts   →  project_memory_chunks   (Stage 5B)         │
│  Per-project decisions   →  design_decisions        (Stage 8)          │
│  Per-user fingerprint    →  architect_profiles      (Stage 8)          │
│  Per-client patterns     →  client_profiles         (Stage 8)          │
│  Global RAG corpus       →  knowledge_chunks        (Stage 6)          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Schema (Stage 8 additions)

### `users` — added column

| Column | Notes |
|---|---|
| `learning_enabled` | `BOOLEAN NOT NULL DEFAULT TRUE`. The privacy switch. When False, the architect-fingerprint extractor and client-profile extractor refuse to run. |

### `projects` — added column

| Column | Notes |
|---|---|
| `client_id` | Nullable FK to `clients(id)` `ON DELETE SET NULL`. Existing rows are unaffected; setting binds the project to a client for the extractor. |

### `clients`

| Column | Notes |
|---|---|
| `id`, `created_at`, `updated_at` | UUID + timestamps |
| `primary_user_id` | FK users (CASCADE) — the architect who owns this client |
| `name`, `contact_email`, `notes` | Display fields |
| `status` | `active` \| `archived` (CHECK constraint) |

### `client_profiles`

| Column | Notes |
|---|---|
| `client_id` | FK clients (CASCADE), **UNIQUE** — one row per client |
| `project_count` | Number of projects this profile aggregates |
| `typical_budget_inr` | JSONB — `{low, high, median, samples}` |
| `recurring_room_types` | JSONB — `[{name, count, share}, ...]` |
| `recurring_themes` | JSONB — same shape |
| `accessibility_flags` | JSONB array of slugs |
| `constraints` | JSONB array of recurring free-form phrases |
| `last_project_at`, `last_extracted_at` | ISO timestamps |

### `architect_profiles`

| Column | Notes |
|---|---|
| `user_id` | FK users (CASCADE), **UNIQUE** — one row per user |
| `project_count` | Number of projects analysed |
| `preferred_themes`, `preferred_materials` | JSONB — `[{name, count, share}, ...]` |
| `preferred_palette_hexes` | JSONB array of `#hex` strings |
| `typical_room_dimensions_m` | JSONB — `{length, width, height}` (medians) |
| `tool_usage` | JSONB — `[{name, count, share}, ...]` |
| `last_project_at`, `last_extracted_at` | ISO timestamps |

### `design_decisions`

| Column | Notes |
|---|---|
| `project_id` | FK projects (CASCADE) |
| `actor_id` | FK users (SET NULL) — the architect or agent |
| `version` | Integer — design-graph version this pertains to (0 if pre-version) |
| `category` | `material` / `layout` / `budget` / `theme` / `mep` / `structural` / `lighting` / `general` |
| `title`, `summary`, `rationale` | Display fields |
| `rejected_alternatives` | JSONB array of `{option, reason_rejected}` dicts |
| `sources` | JSONB array of provenance strings |
| `tags` | JSONB array of free-form tags |

Indexes: `(project_id)`, `(project_id, created_at)` for newest-first
list views.

---

## Privacy contract

`User.learning_enabled` is the kill switch. Default: `True`.

| Action | When `learning_enabled = True` | When `False` |
|---|---|---|
| Architect-fingerprint nightly task | Runs, upserts `architect_profiles` row | **Skipped**. Result: `{ok: True, skipped_reason: "learning_disabled"}`. The existing row stays — it just doesn't get refreshed. |
| Client-profile nightly task | Runs (gated on the architect who owns the client) | Skipped — same shape |
| `get_architect_fingerprint` agent tool | Returns the row | Returns the row + `learning_enabled: false`. The agent surfaces the disabled state to the user. |
| `get_client_profile` agent tool | Returns the row if it exists | Returns the row if it exists — but extractors haven't been refreshing it |
| `record_design_decision` | Always works (decisions aren't a "learned" pattern; they're explicit logs) | Always works |
| `recall_design_decisions` | Always works | Always works |

The flag is read **at the start of every nightly task run**, not
cached. Disabling at any point makes the next run a no-op without
killing in-flight extractions.

When a user disables learning + wants their existing profile
removed, the future settings UI calls `DELETE` on the
`architect_profiles` row directly. The agent tool layer doesn't
expose deletion — that's a one-time admin action.

---

## Extractors

Both extractors are **pure Python**. No LLM. Inputs in, structured
fingerprint out.

### `extract_architect_fingerprint`

Walks the architect's design graphs + tool-usage audit events:

- **Themes** counted (`graph['style']['primary']`).
- **Materials** counted from `graph['materials']` and from
  `objects[*].material` so partial graphs still contribute.
- **Palette hexes** pulled from `graph['style']['palette']` and
  `graph['palette']` (handles both list-of-strings and
  list-of-`{hex}` dicts).
- **Typical room dimensions** = median of length / width / height
  across all projects. Robust to missing dims.
- **Tool usage** counted from audit events with
  `action == "tool_call"`, ignoring other audit actions.

Defensive against:
- Empty input → empty fingerprint with `project_count=0`.
- Style as a bare string instead of a dict.
- Missing `dimensions`, missing `materials`, missing `objects`.

### `extract_client_pattern`

Walks one client's projects:

- **Typical budget** = `{low, high, median, samples}` from each
  project's estimate total. Falls back through several keys
  (`estimate_total_inr` → `estimate.total`).
- **Recurring rooms / themes** counted across projects with
  fallback to `graph_data.room.type` and
  `graph_data.style.primary` when the project doesn't carry a
  flat field.
- **Accessibility flags** pulled from `project.accessibility_flags`
  *and* from decisions tagged `accessibility`.
- **Free-form constraints** — splits descriptions on `;`,
  lowercases, keeps phrases that recur across ≥ 2 projects.

The min-2 threshold on constraints is deliberate: a one-off
description shouldn't graduate to "this client always wants…".

---

## Celery tasks

Both routed to the `ingestion` queue:

```
app.workers.memory_extraction.extract_architect_fingerprint_task
app.workers.memory_extraction.extract_client_profile_task
```

### Inputs / outputs

```python
extract_architect_fingerprint_task.apply_async(kwargs={"user_id": "..."})
# → {"ok": True, "user_id": "...", "project_count": N, "tool_call_samples": M}
# or {"ok": True, "skipped_reason": "learning_disabled", "user_id": "..."}

extract_client_profile_task.apply_async(kwargs={"client_id": "..."})
# → {"ok": True, "client_id": "...", "project_count": N}
```

Both tasks:

- Open their own `AsyncSession` via `async_session_factory`.
- Re-check the privacy flag (it may have flipped since dispatch).
- Auto-retry 3× with exponential backoff on any exception
  (`autoretry_for=(Exception,)`).
- Commit on success; rollback + re-raise on failure.

Convenience dispatchers `dispatch_architect_fingerprint` and
`dispatch_client_profile` swallow broker errors and return `None`
when dispatch fails — same pattern as Stage 5D's auto-indexer.

### Scheduling

Stage 8 doesn't ship a Celery beat schedule — schedule the tasks
externally (cron + the dispatch helpers, or Celery beat config in
the worker entrypoint). A reasonable default is once-per-night
per architect.

---

## Agent tools

Stage 8 adds 5 tools (1 write + 4 read):

| Tool | Type | Audit | Notes |
|---|---|---|---|
| `record_design_decision` | Write | `design_decision` | Append-only — to revise, record a NEW decision |
| `recall_design_decisions` | Read | none | LIKE search across title/summary/rationale + category/version filters |
| `get_architect_fingerprint` | Read | none | Returns `learning_enabled` + `profile_exists` + the structured fingerprint |
| `get_client_profile` | Read | none | Owner-guarded — cross-architect reads return ToolError |
| `resume_project_context` | Read | none | Composite: project + client + recent versions + recent decisions + memory chunk count |

All four read tools are eligible for the Stage-5 parallel
dispatcher (no audit footprint).

### Decision schema

```json
{
  "title": "Picked walnut for island",
  "summary": "Island in walnut after comparing oak.",
  "rationale": "Client prefers darker tones; durability.",
  "category": "material",
  "version": 1,
  "rejected_alternatives": [
    {"option": "oak", "reason_rejected": "too light"}
  ],
  "sources": ["tool_call:cost_engine_abc"],
  "tags": ["client_preference"]
}
```

Recommended pattern: the agent calls `record_design_decision`
**after** a `generate_initial_design` / `apply_theme` /
`edit_design_object` returns successfully. The Stage 5C auto-index
hook handles per-version embedding; the decision adds the *why*
on top.

---

## Test surface

### Unit (`tests/unit/test_stage8_extractors.py`)

- `extract_architect_fingerprint`:
  - Empty input → empty fingerprint
  - Theme / material counting + share computation
  - Typical-dim medians
  - Palette dedup by frequency
  - Tool-usage counting from audit events (filters to `tool_call`)
  - Partial graphs (no room, bare-string style, etc.) don't crash
- `extract_client_pattern`:
  - Empty input
  - Budget low/high/median
  - Recurring room types from both flat + nested fields
  - Accessibility flags from both direct + tag-derived sources
  - Constraint phrases require ≥ 2 occurrences
- Tool registry shape (5 tools registered, audit targets correct,
  required fields, limits)

### Integration (`tests/integration/test_stage8_memory.py`)

- Decision record + recall round-trip
- Decision search matches rationale text
- Unknown category rejected (ToolError)
- `record_design_decision` requires project scope
- Architect fingerprint extractor → DB → tool reads it back
- `_extract_architect_async` skips when `learning_enabled=False`
- `get_architect_fingerprint` returns `profile_exists=False` for
  fresh users
- `get_architect_fingerprint` surfaces `learning_enabled=false`
- Client owner guard — cross-architect reads return ToolError
- `resume_project_context` returns versions newest-first +
  decisions + chunk count

The Celery tasks themselves are exercised via direct calls to
`_extract_architect_async` / `_extract_client_async` — no broker
or worker required.

---

## What's *not* here yet (deferred to 8B)

- **Embedding chat turns for semantic recall.** Currently the
  agent has `recall_recent_chat` (positional) but no semantic
  search across messages. Adding embeddings to `chat_messages`
  needs a write-path patch in Stage 5's persistence module.
- **System-prompt injection of memory at session start.** The
  fingerprint + client profile + project context exist but the
  agent loop doesn't auto-inject them. The agent has to call
  the read tools explicitly. Stage 8B will fold a slim digest
  into the system prompt at session resume.
- **LLM-based session summarisation.** When a chat balloons past
  the context window, an LLM-summarised version should replace
  older turns. Out of scope for Stage 8 — touches the agent
  loop's read path.
- **Celery beat schedule.** Stage 8 ships the tasks; the schedule
  (one-per-night-per-architect) is left to the deployment.
- **Profile delete via agent tool.** The settings UI handles
  GDPR-style deletion directly against the DB.

---

## Operations

### Manually refreshing one architect's fingerprint

```python
from app.workers.memory_extraction import dispatch_architect_fingerprint
task_id = dispatch_architect_fingerprint(user_id="<uuid>")
# Returns the Celery task id (or None if broker is down).
```

Or run the body inline (no Celery needed):

```python
from app.workers.memory_extraction import _extract_architect_async
result = await _extract_architect_async("<uuid>")
print(result)
```

### Disabling learning for a user

```sql
UPDATE users SET learning_enabled = FALSE WHERE id = '<uuid>';
```

The next nightly run will skip; the existing profile row stays.

### Removing an architect's profile entirely

```sql
DELETE FROM architect_profiles WHERE user_id = '<uuid>';
```

The next run with `learning_enabled=True` will recreate it from
scratch.

### Inspecting a profile

```sql
SELECT
  user_id, project_count, last_extracted_at,
  jsonb_array_length(preferred_themes)    AS theme_count,
  jsonb_array_length(preferred_materials) AS material_count,
  typical_room_dimensions_m
FROM architect_profiles
WHERE user_id = '<uuid>';
```
