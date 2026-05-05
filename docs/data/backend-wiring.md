# Backend ↔ Frontend Wiring

> **Status:** Mock backend live and wired end-to-end (chat streaming
> verified). Real Python backend swap-in path documented below.

---

## How the wiring works

The Next.js frontend talks to `http://localhost:8000/api/v1/*` via
[`frontend/lib/api-client.ts`](../../frontend/lib/api-client.ts). The
base URL comes from `NEXT_PUBLIC_API_URL` (defaults to that localhost
path).

Two consumers right now:

| Frontend caller | Endpoint | Method |
|---|---|---|
| `chat.stream()` | `/api/v1/chat/stream` | POST + SSE response |
| `design.generate()` | `/api/v1/projects/:id/generate` | POST |

The frontend doesn't care whether the listener on port 8000 is the
real Python FastAPI or the mock — same wire format, same event shape.
Swap freely.

---

## Mock backend (current — zero install)

Located at [`scripts/mock-backend.mjs`](../../scripts/mock-backend.mjs).
Pure Node.js stdlib (no `npm install`). Implements:

- `GET  /api/v1/health` — `{ status: "ok", mock: true, port }`
- `POST /api/v1/chat/stream` — SSE token streaming with realistic
  per-token jitter (30–90 ms / token, faster on whitespace), final
  `done` event with `suggestions` + `reference_links`
- `POST /api/v1/projects/:id/generate` — fake design graph + estimate
  with totals + line items

### Run it

```bash
node scripts/mock-backend.mjs               # default port 8000
PORT=8001 node scripts/mock-backend.mjs     # override
```

Or via the Claude Code launch.json: `preview_start name="mock-backend"`.

### What it doesn't do

- No real LLM (returns canned responses keyed by mode + prompt keyword)
- No database (each request is independent)
- No auth (no JWT validation)
- No image generation, no RAG, no live feeds, no cost engine

That's fine for verifying the **wiring**. Swap to the real backend for
behaviour.

---

## Real Python backend (target)

When you're ready to replace the mock with the actual FastAPI app —
the one with the agent runtime, RAG, live feeds, cost engine, all 81
tools. Setup:

### 1. Infrastructure

You need:
- Python 3.11+
- PostgreSQL 16 with the `pgvector` extension
- Redis 7

The simplest path is **Docker Compose** — the repo's
[`docker-compose.yml`](../../docker-compose.yml) wires postgres +
redis + migrate + api + worker + beat:

```bash
docker compose up -d
```

Without Docker, install via Homebrew:

```bash
brew install python@3.11 postgresql@16 redis
brew services start postgresql@16
brew services start redis
createdb katha
psql katha -c "CREATE EXTENSION vector;"
```

### 2. .env file

Create `/Users/darshan_workspace/workspace/KATHA-AI/.env`:

```bash
ENVIRONMENT=dev
DATABASE_URL=postgresql+asyncpg://katha:katha@localhost:5432/katha
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# At least one LLM provider key
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-sonnet-4-5
OPENAI_API_KEY=sk-...                  # used by chat_engine + embeddings

# Optional (Stage 12 live feeds)
LIVE_FEEDS_ENABLED=false               # leave off for dev
FEED_SLACK_WEBHOOK_URL=

# Optional (Stage 7 multi-modal)
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=uploads

JWT_SECRET=dev-secret-change-in-prod
```

### 3. Python deps

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4. Migrations

```bash
cd backend
alembic upgrade head
```

This creates all 23 tables (Stage 0 → Stage 13 + Stage 12 feeds + the
upcoming Stage 15 standards seed).

### 5. Start the server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# → {"status":"ok","version":"0.2.0"}
```

### 6. Swap from mock to real

1. Stop the mock: find its PID and kill it, or `Ctrl+C` if running in foreground
2. Start uvicorn (above)
3. The frontend (`http://localhost:3001`) now talks to the real backend — no frontend changes needed

That's it. Same wire format, same port, same SSE shape.

---

## Verifying end-to-end

After either backend is running:

1. Open `http://localhost:3001/chat`
2. Type a prompt, hit Send
3. Watch the response stream in token-by-token
4. After completion, suggestions appear as terracotta chips below the message
5. The conversation appears in the left sidebar (with the terracotta active state on the current sheet)
6. New chats create a new "sheet" entry in the sidebar

**For `/design`:** wire is in place but the generation call is currently
stubbed in the frontend (see [`image-workspace-mvp2.tsx`](../../frontend/components/workspace/image-workspace-mvp2.tsx)
`generate()` function — uses local state instead of the API). Swap to
`design.generate(token, projectId, body)` when you have a project
created and the backend running.

---

## Architecture notes

### Why SSE (not WebSockets)?

- Unidirectional (server → client) is enough for chat streaming
- Native browser support, no library needed
- Auto-reconnect built in
- Backpressure-friendly (server controls pace)
- Reverse-proxy friendly (works through nginx, Cloudflare, etc.)

WebSockets would matter for the future live cost stream and image-gen
progress events — those benefit from bidirectional and binary frames.

### Why `Depends(get_db)` not request-state for sessions?

FastAPI's dependency injection gives a fresh AsyncSession per request,
auto-rolled-back on exception, auto-committed on success. The chat
stream endpoint doesn't currently take a session because the chat
engine doesn't write to DB — but Stage 5 chat persistence will add
that, and the same pattern applies.

### Where the mock falls short

If you're testing anything that depends on:
- Real RAG retrieval (Stage 6)
- Real cost engine (Stage 1 + Stage 12)
- Real reasoning transparency (Stage 11) — citations are canned in mock
- Real generation pipeline (Stage 4 tools)
- Real live feeds (Stage 12)
- Real haptic export (Stage 9)

…you need the actual Python backend running. Use the mock for UX
plumbing verification only.
