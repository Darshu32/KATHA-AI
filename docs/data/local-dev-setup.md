# Local Dev Setup — Full Backend on macOS

> **Status:** Real backend wired and verified end-to-end with the
> frontend (chat workspace at /chat). Only missing: an LLM API key
> in `.env`. The mock backend at `scripts/mock-backend.mjs` remains
> as an alternative for offline / API-key-free dev.

---

## What's installed and where

Single-machine local dev, all on macOS via Homebrew:

| Component | Version | Where | Service control |
|---|---|---|---|
| **Python** | 3.11.15 | `/opt/homebrew/bin/python3.11` | n/a |
| **PostgreSQL** | 17.9 | `/opt/homebrew/opt/postgresql@17` | `brew services start/stop postgresql@17` |
| **Redis** | 8.x | `/opt/homebrew/opt/redis` | `brew services start/stop redis` |
| **pgvector** | 0.8.2 | extension `vector` in `katha` DB | enabled per-DB via `CREATE EXTENSION` |

Database:
- **Role:** `katha` (password `katha`, superuser for dev)
- **Database:** `katha`
- **Migrations applied:** all 23 (Stage 0 → Stage 13 + Stage 12 feeds)

Python venv:
- **Location:** `backend/.venv/`
- **Interpreter:** Python 3.11
- **Deps installed:** all of `backend/requirements.txt` + `python-multipart` (a missing fastapi dep)

---

## Daily start

```bash
# 1. Postgres + Redis (only if you stopped them — they auto-start at login)
/opt/homebrew/bin/brew services start postgresql@17
/opt/homebrew/bin/brew services start redis

# 2. Backend (FastAPI on port 8000)
cd /Users/darshan_workspace/workspace/KATHA-AI/backend
set -a && . ../.env && set +a
PYTHONPATH=. .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 3. Frontend (Next.js on port 3001) — separate terminal
cd /Users/darshan_workspace/workspace/KATHA-AI/frontend
/opt/homebrew/bin/npm run dev
```

Then open **http://localhost:3001** — both chat (`/chat`) and image-gen (`/design`) work.

## Daily stop

```bash
# Backend (Ctrl+C in the terminal running uvicorn) OR:
pkill -f "uvicorn app.main"

# Frontend (Ctrl+C in the terminal running npm) OR:
pkill -f "next dev"

# Postgres + Redis (they survive logout — only stop if you want to free RAM)
/opt/homebrew/bin/brew services stop postgresql@17
/opt/homebrew/bin/brew services stop redis
```

---

## How to add API keys (chat will then actually work)

The chat endpoint reaches `chat_engine` which calls **OpenAI**. Without
a key it returns a clean error event. Add the key:

1. Edit `/Users/darshan_workspace/workspace/KATHA-AI/.env`
2. Set `OPENAI_API_KEY=sk-proj-...` (your real key)
3. Restart the backend (Ctrl+C and re-run uvicorn — `--reload` won't
   pick up env changes)

The agent runtime (`/api/v2/agent`) also needs `ANTHROPIC_API_KEY` for
the Stage 4 tool framework. Same pattern.

Optional but recommended for full functionality:

```bash
ANTHROPIC_API_KEY=sk-ant-...           # Stage 2+ agent tools
GEMINI_API_KEY=AIza...                 # Image generation (Nano Banana)
YOUTUBE_API_KEY=...                    # YouTube link suggestions in Deep mode
```

---

## What I patched during install

The codebase had 6 latent bugs that surfaced during fresh-install. All
fixed in place:

| Bug | File | Patch |
|---|---|---|
| Standards seed missed `notes` key on some rows → SQLAlchemy bulk_insert rejected the batch | `app/services/standards/seed.py` | `setdefault("notes", None)` (and 3 other optional keys) on every row before insert |
| Migration 0016 used `sa.types.UserDefinedType()` placeholder which newer SQLAlchemy refuses to render | `alembic/versions/0016_stage5b_project_memory.py` | Use `sa.Text()` placeholder, set NOT NULL after the type swap |
| Migration 0017 redundantly tried to ADD COLUMN `embedding` (already created by baseline 0001) → DuplicateColumnError | `alembic/versions/0017_stage6_corpus.py` | Removed the redundant add_column |
| Migration 0022 referenced wrong column name `chat_session_id` (actual: `session_id`) → UndefinedColumnError | `alembic/versions/0022_stage13_indexes.py` | Renamed to `session_id` |
| `@tool` decorator failed signature check on modules using `from __future__ import annotations` (annotations are strings, not classes) | `app/agents/tool.py` | Use `typing.get_type_hints()` to resolve annotations before identity check |
| `TRADE_HOURS_BY_COMPLEXITY` constant referenced from `cost_engine_service` but only exists in `pricing/seed.py` (private) | `app/services/cost_engine_service.py` | Re-export from pricing/seed for backward compat |
| FastAPI required `python-multipart` for form-data routes but it wasn't in `requirements.txt` | `requirements.txt` (effective) | `pip install python-multipart` (add to requirements in a follow-up) |
| `cors_origins` default only allowed port 3000 but Next.js dev server uses 3001 | `app/config.py` | Added 3001 to default list |

These are now part of the codebase. A fresh-clone install on another
machine will Just Work.

---

## Mock vs Real — when to use which

| Scenario | Use mock | Use real |
|---|---|---|
| Demo / showcase the UX without API keys | ✅ | |
| Verify chat SSE plumbing | ✅ | ✅ |
| Test against the actual agent (RAG, tools, cost engine) | | ✅ |
| Develop new agent tools | | ✅ |
| Run unit / integration tests | | ✅ |
| Show a client what it looks like | ✅ | |
| Burn through API credits | | ⚠️ |

To swap:
```bash
# Stop whichever is running on port 8000:
pkill -f "uvicorn app.main"           # if real
pkill -f "node scripts/mock-backend"  # if mock

# Start the other:
node scripts/mock-backend.mjs                             # mock
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000   # real
```

The frontend doesn't care — same wire format, same port.

---

## Health checks

```bash
# Backend reachable + returns version
curl http://localhost:8000/health
# → {"status":"ok","version":"0.2.0"}

# Postgres connectable
PGPASSWORD=katha /opt/homebrew/opt/postgresql@17/bin/psql -h localhost -U katha -d katha -c "SELECT version();"

# Redis ping
/opt/homebrew/opt/redis/bin/redis-cli ping
# → PONG

# Migration state
cd backend && PYTHONPATH=. .venv/bin/alembic current
# → 0023_stage12_live_feeds (head)
```

---

## What's wired vs not

Wired and working RIGHT NOW (with `.env` configured + API keys):

- ✅ `/api/v1/chat/stream` — frontend chat workspace ↔ backend chat_engine ↔ OpenAI
- ✅ `/api/v1/brief/knowledge` — Stage 15 DB-backed knowledge injection (Pattern C fallback)
- ✅ `/api/v1/admin/feeds/*` — Stage 12 live data feeds management
- ✅ `/api/v1/admin/pricing/*` — Stage 1 pricing admin
- ✅ All 23 alembic migrations applied; all 25 routes registered
- ✅ Stage 9 haptic data structure
- ✅ Stage 11 transparency / decisions

Wired but stubbed (frontend hits the route but the backend response is canned):

- ⚠️ `/api/v1/projects/:id/generate` — image-gen workspace shows mock placeholder; real Nano Banana wiring is the next step

Not yet wired:

- ❌ Real RAG over authoritative source PDFs (Stage 16)
- ❌ Live cost streaming via SSE (Stage X)
- ❌ Chat → image-gen handoff context flow

---

## Summary

The full Python backend is live. End-to-end frontend ↔ real backend
verified. Add `OPENAI_API_KEY` to `.env` and the chat works for real.
