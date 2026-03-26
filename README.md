# KATHA AI

KATHA AI is an architecture and interior design platform built around a shared design graph. The repository starts with a monorepo-style foundation so we can evolve the product without repainting the base every week.

## Workspace layout

- `apps/web` contains the Next.js frontend shell.
- `apps/api` contains the FastAPI backend shell.
- `packages/design-graph` contains shared TypeScript models for the canonical design graph.
- `docs` contains product and implementation notes.

## Product direction

The core principle is simple:

1. Build a structured design graph first.
2. Derive 2D views, 3D views, and estimates from that graph.
3. Keep object IDs stable so local edits stay synchronized.

## Getting started

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

### Backend

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Near-term MVP goals

- Prompt input and design intent capture
- Design graph creation and persistence
- 2D concept and 3D scene placeholders
- Version-aware project dashboard
- Material and estimate panels

