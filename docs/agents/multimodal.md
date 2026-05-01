# Stage 7 — Multi-modal Inputs

> **Audience:** future-you wiring a new vision purpose, debugging an
> upload, switching the storage backend, or adding voice. Read after
> `docs/agents/runtime.md` and `docs/agents/memory.md`.

---

## What Stage 7 added

Architects work visually. The agent now accepts **images** —
site photos, references, mood boards, hand sketches, printed
floor plans — through a thin upload surface plus 5 vision tools
that read the bytes and return structured analyses.

```
┌────────────────────────────────────────────────────────────────────────┐
│                              client                                    │
│        POST /v2/uploads (multipart) ───────────────────────────┐        │
│            │                                                    │       │
│            ▼ asset_id                                           │       │
│        agent chat ("analyze this site photo")                   │       │
│            │                                                    │       │
└────────────┼────────────────────────────────────────────────────┼───────┘
             │                                                    │
             ▼                                                    ▼
       agent loop                                        StorageBackend
             │                                          (local | s3)
       analyze_image(asset_id, purpose)
             │
             ▼
       VisionAnalyzer
             │  resolve owner-guarded asset ──► UploadRepository
             │  read bytes ───────────────────► StorageBackend
             │  pick prompt + JSON schema ──► prompt_for_purpose
             │  call provider                 ▼
             │                            VisionProvider
             │                            (anthropic | stub)
             ▼
       VisionAnalysisOutput { parsed, assets, provider, … }
```

---

## Module map

```
backend/app/
├── storage/                                NEW — backend abstraction
│   ├── __init__.py
│   ├── base.py                             StorageBackend ABC + StoredAsset
│   ├── local.py                            LocalStorageBackend (filesystem)
│   ├── s3.py                               S3StorageBackend (boto3)
│   └── factory.py                          get_storage_backend()
├── vision/                                 NEW — vision pipeline
│   ├── __init__.py
│   ├── base.py                             VisionProvider ABC + types
│   ├── prompts.py                          5 purpose-specific prompts + schemas
│   ├── anthropic_vision.py                 Claude Vision (production)
│   ├── stub.py                             StubVisionProvider (tests)
│   ├── factory.py                          get_vision_provider()
│   └── analyzer.py                         VisionAnalyzer orchestrator
├── routes/uploads.py                       NEW — POST/GET/DELETE/LIST upload routes
├── repositories/uploads/upload_repo.py     NEW — UploadRepository
├── agents/tools/vision.py                  NEW — 5 vision agent tools
└── models/orm.py                           + UploadedAsset

backend/alembic/versions/0018_stage7_uploaded_assets.py   uploaded_assets table
```

---

## Schema

`uploaded_assets`

| Column | Notes |
|---|---|
| `id` | UUID PK |
| `owner_id` | FK users (CASCADE) |
| `project_id` | Optional FK projects (SET NULL) |
| `kind` | `image` / `site_photo` / `reference` / `mood_board` / `hand_sketch` / `existing_floor_plan` / `audio` / `other` |
| `storage_backend` | `local` / `s3` — which backend the bytes live in |
| `storage_key` | Opaque key the backend uses |
| `original_filename`, `mime_type`, `size_bytes`, `content_hash` | As supplied / computed at upload |
| `status` | `uploading` / `ready` / `error` (CHECK) |
| `error_message` | When status = `error`, the failure reason |
| `metadata` | JSONB — sha256, EXIF (future), etc. |

CHECK: `size_bytes >= 0`. Indexes on `owner_id`, `project_id`,
`(owner_id, created_at)` for the chat list view.

---

## Storage backends

`StorageBackend` ABC has four methods:

| Method | Purpose |
|---|---|
| `put_bytes(*, key, data, mime_type)` | Idempotent write |
| `get_bytes(key)` | Read; raises `StorageError` on miss |
| `delete(key)` | Idempotent (no-op when missing) |
| `presigned_url(key, ...)` | Optional — `None` for backends without |
| `exists(key)` | Cheap existence check |

### `LocalStorageBackend`

Writes to `settings.storage_local_root` (default `./uploads`).
Suitable for solo dev + integration tests; not for multi-instance
production. Path traversal is blocked at the `_sanitise_key`
boundary — keys are forced to lowercase, restricted to
`[a-z0-9-_./]`, and rejected outright if they contain `..` or null
bytes.

### `S3StorageBackend`

Wraps boto3 against any S3-compatible API (AWS S3 / Cloudflare R2 /
MinIO). Configured via `s3_endpoint`, `s3_access_key`,
`s3_secret_key`, `s3_bucket`, `s3_region`. Cloudflare R2 needs
`region="auto"` and the R2 endpoint URL.

Both backends run blocking I/O via `asyncio.to_thread` so the event
loop stays responsive.

### Choosing a backend

`settings.storage_backend = "local" | "s3"` (default: `local`).
Unknown values fall back to local + log a warning. The factory
memoises the result so the S3 client is built once.

---

## Vision providers

| Class | Use | Notes |
|---|---|---|
| `AnthropicVisionProvider` | Production | Claude (default `claude-sonnet-4-5`); base64-encodes images, lazy-imports the SDK |
| `StubVisionProvider` | Tests + offline dev | Deterministic per-purpose fixtures; can override individual fixtures |

`get_vision_provider()` returns Anthropic when `ANTHROPIC_API_KEY`
is set; otherwise the stub with a logged warning.

### JSON-output contract

Anthropic doesn't have OpenAI-style strict JSON-schema mode, so
the prompt asks for JSON only and we parse defensively via
`_extract_json` — which:

1. Tries `json.loads` directly.
2. Strips ```json ...``` code fences if present.
3. Walks the text counting brace depth to find a balanced top-level
   object.
4. Returns `None` (and the caller raises `VisionError`) if no valid
   JSON is found.

Tested against clean JSON, fenced JSON, and chatty replies that
embed an object in surrounding prose.

---

## The 5 purposes

Each purpose carries a system prompt, user template, and JSON
output schema. Schemas live in `app/vision/prompts.py` and are
imported by the agent tools' output-shape checks.

### `site_photo`

Survey a single site photo. Output:

```python
{
  "summary": str,
  "orientation": {"facing": str, "confidence": float, "rationale": str},
  "surroundings": [{"kind": str, "side": str, "note": str}, ...],
  "lighting": str,
  "vegetation": [str, ...],
  "scale_clues": [str, ...],
  "watch_outs": [str, ...],
}
```

### `reference`

Extract aesthetic from a single reference image. Output:

```python
{
  "summary": str,
  "palette": [{"name": str, "hex": str, "role": str}, ...],
  "materials": [{"category": str, "specifics": str, "finish": str}, ...],
  "era_or_movement": str,
  "style_tags": [str, ...],
  "signature_moves": [str, ...],
  "watch_outs": [str, ...],
}
```

### `mood_board`

Same shape as `reference` but synthesises across multiple images
(2–8). The model is asked to produce ONE common aesthetic, with
conflicts called out in `watch_outs`.

### `hand_sketch`

Convert a hand sketch into a structured DesignGraph. Output:

```python
{
  "summary": str,
  "confidence": float,
  "room": {"type": str, "dimensions": {...}, "label": str},
  "objects": [{"id", "type", "position", "dimensions", "rotation_deg"}, ...],
  "openings": [{"kind", "wall", "width_mm", "position_normalised"}, ...],
  "watch_outs": [str, ...],
}
```

### `existing_floor_plan`

Same DesignGraph shape as `hand_sketch`, but the model is told the
plan is authoritative — be precise rather than creative.

---

## Agent tools

Stage 7 adds 5 read-only tools (eligible for the Stage-5 parallel
dispatcher):

| Tool | Purpose | Output |
|---|---|---|
| `analyze_image` | foundational; takes `purpose` | `VisionAnalysisOutput` |
| `analyze_site_photo` | sugar around `purpose=site_photo` | site survey |
| `extract_aesthetic` | 1 image → reference; 2-8 → mood_board | aesthetic |
| `sketch_to_floor_plan` | sugar around `purpose=hand_sketch` | DesignGraph |
| `digitize_floor_plan` | sugar around `purpose=existing_floor_plan` | DesignGraph |

All five share `VisionAnalysisOutput`:

```python
{
  "purpose": str,                 # one of the 5 supported slugs
  "provider": str,                # 'anthropic_vision' | 'stub_vision'
  "model": str,
  "input_tokens": int,
  "output_tokens": int,
  "assets": [AssetRef, ...],      # which uploads participated
  "parsed": {...},                # purpose-specific structured output
}
```

### Owner guard

Every tool requires `ctx.actor_id` and refuses to analyse uploads
owned by anyone else. The `VisionAnalyzer` enforces this at the
DB layer via `UploadRepository.get_for_owner`.

---

## REST surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/v2/uploads` | Multipart upload — file, kind, optional project_id |
| `GET` | `/api/v1/v2/uploads` | List the user's recent uploads |
| `GET` | `/api/v1/v2/uploads/{id}/content` | Proxy bytes (owner-guarded) |
| `DELETE` | `/api/v1/v2/uploads/{id}` | Remove row + storage bytes |

### Upload lifecycle

1. Client `POSTs` multipart form with `file`, `kind`, optional `project_id`.
2. Route validates MIME against `settings.upload_allowed_mime`,
   enforces `settings.upload_max_bytes`, hashes the bytes (sha256).
3. Inserts the row with `status="uploading"`, then writes via the
   storage backend.
4. Flips status to `ready` (or `error`) and commits.
5. Returns `{id, kind, mime_type, size_bytes, content_url, presigned_url}`.

The `presigned_url` is only populated when the storage backend
supports it (S3 yes, local no). Clients fall back to
`content_url` (the proxy route).

### Allowed MIME types

`image/jpeg`, `image/png`, `image/webp`, `image/heic`, `image/heif`.
Default cap: 25 MB. Both knobs are configurable via
`upload_allowed_mime` and `upload_max_bytes`.

---

## Testing

### Unit (`tests/unit/test_stage7_*`)

- `test_stage7_storage.py` — local backend round-trip, `_sanitise_key`,
  factory.
- `test_stage7_vision.py` — prompt selection, stub provider fixtures,
  JSON extraction helper, tool registry shape.

### Integration (`tests/integration/test_stage7_*`)

- `test_stage7_uploads_and_vision.py` — real Postgres + temp-dir
  local storage + `StubVisionProvider`. Covers:
  - Upload repo lifecycle.
  - Owner guard isolates users.
  - Vision analyzer round-trip.
  - Each of the 5 vision tools through `call_tool`.
  - Cross-owner access returns ToolError.
  - Wrong status (`uploading`) is rejected.

The S3 backend is not exercised in tests — its contract matches
`LocalStorageBackend` and is verified manually against R2 in dev.

---

## What's *not* here yet (deferred to 7B)

- **Voice notes (Whisper).** The `kind="audio"` slug is in the schema
  but no transcription pipeline exists. Plan: `POST /v2/uploads`
  accepts the audio, a Celery task transcribes via OpenAI Whisper,
  the transcript is fed to the agent as context.
- **Image generation (Gemini).** The plan calls for
  `render_design_concept(graph_id, style, view)`. That's a
  fundamentally different flow — generation, not analysis. Build it
  alongside the existing image exporters when needed.
- **OCR for plans with complex labels.** The `existing_floor_plan`
  prompt assumes the model can read embedded text. A scanned-and-
  noisy plan may need a Tesseract pre-pass.
- **EXIF metadata extraction.** GPS coordinates, capture time, focal
  length — useful for site photos. Currently we only store the file's
  sha256 in metadata.
- **Chunking large reference sets.** `extract_aesthetic` caps at 8
  images per call. A larger mood board needs a separate aggregation
  pass.

---

## Operations

### Switching storage backends

```bash
# Local dev (default).
export STORAGE_BACKEND=local
export STORAGE_LOCAL_ROOT=./uploads

# Production with R2.
export STORAGE_BACKEND=s3
export S3_BUCKET=katha-prod-uploads
export S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
export S3_ACCESS_KEY=...
export S3_SECRET_KEY=...
export S3_REGION=auto
```

The factory memoises the choice; restart the app after changing.

### Migrating existing uploads to S3

The `UploadedAsset.storage_backend` column tracks where the bytes
live. To migrate:

```python
async with async_session_factory() as db:
    rows = await UploadRepository.list_for_owner(
        db, owner_id="...", limit=1000,
    )
    s3 = S3StorageBackend(...)
    local = LocalStorageBackend(...)
    for row in rows:
        if row.storage_backend != "local":
            continue
        data = await local.get_bytes(row.storage_key)
        await s3.put_bytes(
            key=row.storage_key, data=data, mime_type=row.mime_type,
        )
        row.storage_backend = "s3"
    await db.commit()
```

### Inspecting an upload

```sql
SELECT id, kind, mime_type, size_bytes, status, original_filename
FROM uploaded_assets
WHERE owner_id = '<user-id>'
ORDER BY created_at DESC
LIMIT 20;
```

The actual bytes can be read via `GET /api/v1/v2/uploads/{id}/content`
(owner-authenticated) or via direct backend access for ops.
