# Stage 3F — Chat Suggestion Chips Externalization

> **Audience:** future-you adding new prompt chips, A/B testing chip
> copy, or onboarding the design team to chip rotation.

---

## What Stage 3F added

The 4 hardcoded chips that lived in
`frontend/components/chat/suggestion-chips.tsx` (`DEFAULT_SUGGESTIONS`)
are now **DB-backed** and admin-editable. Designers can:

- Update chip copy without a frontend deploy
- Promote / demote chips via `weight`
- Tag chips with `contexts` so different surfaces get different chips
  (chat empty hero, brief intake flow, post-cost-engine follow-up, …)
- Run A/B tests by toggling `status` between `draft` and `published`
- View full version history with audit attribution

The frontend keeps a **one-chip last-ditch fallback** so the empty
hero never renders empty even in offline / network-error scenarios.

---

## Schema

```
suggestions
├─ id                  uuid hex
├─ slug                "modern_villa_facade_ideas"     ← logical key
├─ label               "Modern villa facade ideas"
├─ prompt              full prompt text dispatched to the agent on click
├─ description         optional internal note (not user-visible)
├─ contexts            ARRAY[String]   — e.g. ["chat_empty_hero"]
│                       (empty array = global, surfaces in any context)
├─ weight              integer 0–1000  — higher surfaces earlier (default 100)
├─ status              draft | published | archived
├─ tags                ARRAY[String]   — analytics + filtering
└─ <Stage-0 conventions>:
   deleted_at, version, is_current, previous_version_id,
   effective_from, effective_to, source, source_ref, created_by
```

Partial unique index: `(slug) WHERE is_current=TRUE AND deleted_at IS NULL`
guarantees one current version per slug.

---

## API surface

### Public endpoint (no auth)

```bash
GET /api/v1/suggestions?context=chat_empty_hero&limit=12
```

Response:

```json
{
  "suggestions": [
    {
      "slug": "modern_villa_facade_ideas",
      "label": "Modern villa facade ideas",
      "prompt": "Suggest modern villa facade design ideas with clean lines, ...",
      "weight": 100,
      "tags": ["facade", "modern", "villa"]
    },
    ...
  ],
  "context": "chat_empty_hero",
  "count": 4
}
```

- `Cache-Control: public, max-age=60` — chips don't change often.
- Sorted by `weight DESC, slug ASC` server-side; frontend renders in order.
- Returns the built-in fallback chip if the DB has no published rows
  (fresh dev environment).

### Admin endpoints (auth-protected)

```bash
# Browse — pass ?status=draft|published|archived|all
GET    /api/v1/admin/suggestions
GET    /api/v1/admin/suggestions/{slug}
GET    /api/v1/admin/suggestions/{slug}/history

# Create a new chip (status defaults to draft)
POST   /api/v1/admin/suggestions
       body: { slug, label, prompt, contexts, weight, status, tags, reason }

# Update an existing chip (creates a new version)
POST   /api/v1/admin/suggestions/{slug}
       body: { label?, prompt?, contexts?, weight?, tags?, reason? }

# Status transition
POST   /api/v1/admin/suggestions/{slug}/status
       body: { new_status: "draft" | "published" | "archived", reason? }
```

Every write emits an `AuditEvent` with full before/after diff +
actor + reason + request id.

---

## Lifecycle

```
   POST /admin/suggestions      ── creates ──▶ draft (v1)
            │
            │ POST /admin/suggestions/{slug}/status {new_status: "published"}
            ▼
        published (v2)  ◀── visible to /api/v1/suggestions endpoint
            │
            │ POST /admin/suggestions/{slug}  body: {label: "Better copy", reason: "A/B"}
            ▼
        published (v3)  ◀── frontend automatically picks up new copy
            │
            │ POST /admin/suggestions/{slug}/status {new_status: "archived"}
            ▼
         archived (v4) ── no longer surfaces; history preserved
```

Soft-deleted chips (via `BaseRepository.soft_delete`) stay in
history but never surface anywhere.

---

## Frontend integration

`frontend/components/chat/suggestion-chips.tsx` now:

```tsx
useEffect(() => {
  fetch(`${API_BASE}/suggestions?context=${context}`)
    .then(r => r.json())
    .then(data => setChips(data.suggestions.map(...)));
}, [context]);
```

Defaults `context` to `"chat_empty_hero"`. Caller can pass a
different context (e.g. `"brief_intake"`) for different surfaces.

If the fetch fails, the component keeps a 1-chip built-in fallback
so the UX doesn't break.

---

## Common operations

### Add a new chip via API

```bash
curl -X POST /api/v1/admin/suggestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "slug": "biophilic_office_design",
    "label": "Biophilic office design",
    "prompt": "How can we incorporate biophilic design principles in office spaces?",
    "contexts": ["chat_empty_hero"],
    "weight": 110,
    "status": "published",
    "tags": ["biophilia", "office", "wellness"],
    "reason": "Q2 2026 wellness campaign"
  }'
```

Frontend picks it up on the next `/suggestions` fetch (max 60s lag
due to `Cache-Control`).

### Promote a chip (boost weight)

```bash
curl -X POST /api/v1/admin/suggestions/sustainable_material_options \
  -d '{"weight": 150, "reason": "Sustainability month"}'
```

### Retire a chip

```bash
curl -X POST /api/v1/admin/suggestions/old_chip_slug/status \
  -d '{"new_status": "archived", "reason": "Replaced by v2"}'
```

### Add a context to an existing chip

```bash
# Append: fetch existing first then re-POST with full contexts list.
curl /api/v1/admin/suggestions/modern_villa_facade_ideas    # see current contexts
curl -X POST /api/v1/admin/suggestions/modern_villa_facade_ideas \
  -d '{"contexts": ["chat_empty_hero", "brief_intake"], "reason": "Surface in brief flow too"}'
```

---

## A/B testing flow (Stage 4+ admin UI will simplify this)

1. Clone an existing chip slug → new draft variant.
2. Publish the variant; demote (lower weight) the original.
3. Watch analytics; if variant wins → archive original.
4. If variant loses → promote original back, archive variant.

For now the variant slug must be unique (e.g. add suffix `_v2`).
Stage 13 UI will streamline this.

---

## Migration runbook

```bash
# Fresh DB
alembic upgrade head    # applies 0013 (schema) + 0014 (seed)

# Already on Stage 3E
alembic upgrade head    # applies just 0013 + 0014

# Verify
curl /api/v1/suggestions?context=chat_empty_hero
# Expect 4 published chips
```

Re-running the seed on a database with admin edits is safe — the
unique constraint blocks duplicates and the `WHERE source LIKE
'seed:frontend%'` downgrade only deletes seed-tagged rows.

---

## What's still hardcoded after Stage 3F

| Knowledge source | Status |
|---|---|
| `themes.py` | ✅ DB-backed (Stage 3A) |
| `clearances.py`, `space_standards.py` | ✅ DB-backed (Stage 3B) |
| `mep.py` | ✅ DB-backed (Stage 3C) |
| `manufacturing.py` | ✅ DB-backed (Stage 3D) |
| `codes.py`, `ibc.py`, `structural.py`, `climate.py`, `ergonomics.py` | ✅ DB-backed (Stage 3E) |
| **Frontend `DEFAULT_SUGGESTIONS`** | ✅ **DB-backed (Stage 3F)** |
| `materials.py` (physical props — density, MOR, MOE) | ✅ Stays in code — physics constants |
| `costing.py`, `regional_materials.py` | ✅ DB-backed (Stage 1, separate `material_prices` / `cost_factors` tables) |
| `variations.py`, `summary.py` | Stay in code — pure logic / prompt builders |

**Stage 3 complete.** The only Python data left is physics + formulas
+ pure orchestration logic.

---

## Gotchas for future-you

- **Adding a new context?** Just start tagging chips with the new
  slug (e.g. `cost_followup`) and have the frontend fetch with
  `?context=cost_followup`. No schema change needed.
- **Empty contexts array** = global. Use sparingly; most chips should
  be explicit about where they belong.
- **Caching** — frontend fetches each render but server returns
  `Cache-Control: max-age=60`. Browser caches it; admin updates take
  up to a minute to surface to existing tabs. Push a cache-buster
  query if you ever need instant rotation (Stage 13).
- **Don't edit `frontend/components/chat/suggestion-chips.tsx` to
  add chips.** Use the admin endpoint. The fallback array there is
  intentionally just one chip — anything more drifts from DB truth.
