# Stage 3A — Themes Externalization

> **Audience:** future-you adding themes, debugging style application,
> or onboarding designers to the admin UI.

---

## What Stage 3A added

The 4 BRD theme rule packs (`pedestal`, `mid_century_modern`,
`contemporary`, `modern`) plus the open `custom` palette have been
moved out of `app/knowledge/themes.py` (Python dict) into the `themes`
DB table.

Senior designers can now:
- Edit any theme from `/admin/themes/<slug>` (creates a new version)
- Clone an existing theme into a fresh draft (`Modern → Modern Luxe`)
- Stage themes via `draft → published → archived` workflow
- View full version history with audit attribution

The cost engine (Stage 1) and agent loop (Stage 2) read themes from
the DB now — admin updates are visible **immediately** without any
deploy.

---

## Schema

```
themes
├─ id                  uuid hex
├─ slug                "mid_century_modern"            ← logical key
├─ display_name        "Mid-Century Modern"
├─ era                 "1945-1965 revival"
├─ description         "Era: … · Primary materials: …"
├─ status              draft | published | archived
├─ rule_pack           JSONB — proportions, palette, hardware,
│                              signature_moves, dos, donts, …
├─ aliases             ARRAY[String] — ["midcentury","mcm",…]
├─ cloned_from_slug    nullable; lineage for cloned variants
├─ preview_image_keys  ARRAY[String] — Stage 7 multimodal hooks
└─ <Stage-0 conventions>:
   deleted_at, version, is_current, previous_version_id,
   effective_from, effective_to, source, source_ref, created_by
```

Partial unique index `(slug) WHERE is_current=TRUE AND deleted_at IS NULL`
guarantees one current version per slug.

---

## Common operations

### Browse themes (admin)

```bash
# Published only (default)
GET /admin/themes

# All including drafts/archived
GET /admin/themes?status=all

# Drafts only (designer's working set)
GET /admin/themes?status=draft
```

### Get one theme

```bash
GET /admin/themes/mid_century_modern
GET /admin/themes/mcm                    # alias resolution works
```

### View history

```bash
GET /admin/themes/modern/history
```

Returns every version (newest first) with the actor + reason that
recorded each change.

### Update a rule pack

```bash
POST /admin/themes/modern \
  -H "Content-Type: application/json" \
  -d '{
    "rule_pack": {
      "era": "1920s-1950s international style",
      "proportions": { "form": "balanced modular", ... },
      "material_palette": { "primary": ["oak","walnut","steel"], ... },
      "hardware": { ... },
      "colour_palette": [...],
      "signature_moves": [...],
      "dos": [...],
      "donts": [...]
    },
    "display_name": "Modern (revised)",
    "aliases": ["bauhaus", "international_style"],
    "reason": "May 2026 — added bauhaus alias, expanded materials"
  }'
```

Behind the scenes:
1. Existing `modern` row → `is_current=False`, `effective_to=NOW()`.
2. New row → `version+1`, `is_current=True`, `previous_version_id=<old>`,
   `source='admin'`, `created_by=<user>`.
3. `audit_events` row with full before/after diff.

### Clone a theme

```bash
POST /admin/themes/modern/clone \
  -d '{
    "new_slug": "modern_luxe",
    "new_display_name": "Modern Luxe",
    "reason": "premium variant for hotel project"
  }'
```

Result: a new logical record with `version=1`, `status=draft`,
`cloned_from_slug=modern`. Rule pack is a deep copy. Designer iterates,
then publishes:

```bash
POST /admin/themes/modern_luxe/status \
  -d '{"new_status": "published", "reason": "approved"}'
```

### Archive a theme

```bash
POST /admin/themes/modern/status \
  -d '{"new_status": "archived", "reason": "consolidated into modern_v2"}'
```

Archived themes don't surface to public lookups but stay in history
and audit. Use `status=all` queries to find them.

---

## How the cost engine + agent see themes now

```
                  ┌─────────────────────────────────────┐
                  │ /v2/chat — agent calls              │
                  │   estimate_project_cost(            │
                  │      theme="mid_century_modern", …) │
                  └─────────────────┬───────────────────┘
                                    │
                                    ▼
                  ┌─────────────────────────────────────┐
                  │ build_cost_engine_knowledge         │
                  │   ↓                                  │
                  │ get_theme(session, "mcm")            │
                  └─────────────────┬───────────────────┘
                                    │
              ┌─────────────────────┴────────────────────┐
              │                                          │
              ▼                                          ▼
   ┌─────────────────────────┐           ┌──────────────────────────┐
   │ ThemeRepository         │           │ Legacy themes.get()      │
   │ .get_active_by_slug     │  None ──► │  fallback for fresh-DB   │
   │ (with alias resolution) │           │  / dev environments      │
   └────────────┬────────────┘           └────────────┬─────────────┘
                │                                     │
                └─────────────────┬───────────────────┘
                                  ▼
                       Same dict shape returned
                       (display_name, material_palette,
                        hardware, signature_moves, dos, donts, …)
                                  ▼
                       Cost engine prompt unchanged
```

Existing 25+ services that still import `app.knowledge.themes`
synchronously continue to work — they read the legacy literal, which
is preserved as a fallback. They'll migrate gradually as later stages
wrap them as agent tools.

---

## Aliases (the resolver story)

Designers and architects type all kinds of variations:

```
"midcentury", "mid-century", "Mid Century", "MCM", "mcm"  → mid_century_modern
"plinth", "Theme V", "theme_v"                            → pedestal
```

Stage 3A stores aliases as an array on each theme row. The repository's
`get_active_by_slug` query is:

```sql
SELECT *
  FROM themes
 WHERE is_current = TRUE
   AND deleted_at IS NULL
   AND status = 'published'
   AND (slug = :key OR :key = ANY(aliases))
```

One indexed query, one round-trip.

To add a new alias to an existing theme:

```bash
POST /admin/themes/mid_century_modern \
  -d '{
    "rule_pack": <unchanged or updated>,
    "aliases": ["midcentury", "mcm", "midmod", "mc-modern"]
  }'
```

(The full aliases list goes in — it replaces the old list. To append,
fetch the row first and merge client-side.)

---

## Migration runbook (existing dev DB)

```bash
# Fresh DB
alembic upgrade head    # all migrations including 0004 + 0005

# Already on Stage 1
alembic upgrade head    # applies 0004 (schema) + 0005 (seed)

# Verify
curl /admin/themes
# should return 5 themes: pedestal, mid_century_modern, contemporary, modern, custom
```

**Re-seeding after an admin edit?** Don't. The seed migration deletes
only `WHERE source LIKE 'seed:%'`, so admin edits survive a downgrade
+ upgrade cycle, but you'll have *both* an admin row and the seed row
as separate versions. Cleaner to manually `DELETE` the rows you want
to reset before re-running.

---

## What's still hardcoded after Stage 3A

| Knowledge file | Status | Migrates in… |
|---|---|---|
| `themes.py` | ❌ DB-backed (this stage) | ✅ Stage 3A |
| `clearances.py` | ✅ Still hardcoded | Stage 3B |
| `space_standards.py` | ✅ Still hardcoded | Stage 3B |
| `mep.py` | ✅ Still hardcoded | Stage 3C |
| `manufacturing.py` | ✅ Still hardcoded | Stage 3D |
| `codes.py`, `ibc.py` | ✅ Still hardcoded | Stage 3E |

---

## Quick checklist for adding a new theme via UI (Stage 13)

1. Pick a "starting point" theme to clone from (or start blank).
2. `POST /admin/themes/<source>/clone` with new slug + display name.
3. Iterate on the rule pack via `POST /admin/themes/<new_slug>`.
4. Publish: `POST /admin/themes/<new_slug>/status` `{"new_status":"published"}`.
5. Architect can immediately reference it in `/v2/chat` — no deploy.

---

## Gotchas for future-you

- [ ] Adding fields to a rule pack? You don't need a migration —
      `rule_pack` is JSONB. Just update the cost-engine system prompt
      to expect the new field.
- [ ] Adding a new top-level theme column? Migration required
      (numbered `0006_…`). Update the model, the seed builder, and
      the admin endpoint payload schema.
- [ ] Deleting a theme? Soft-delete only. Use `archived` status for
      "out of catalogue" or `deleted_at` for fully removed.
- [ ] Past estimates referenced an archived theme? They still work —
      pricing snapshots captured the rule pack at generation time, so
      rerunning the snapshot reproduces the original numbers.
