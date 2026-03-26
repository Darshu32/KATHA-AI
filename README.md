# KATHA AI

KATHA AI is an architecture and interior design platform built around a shared design graph. The repository starts with a monorepo-style foundation so we can evolve the product without repainting the base every week.

## Workspace layout

- `frontend` contains the Next.js frontend shell.
- `backend` contains the FastAPI backend shell.
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
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
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

## Prompt contracts

The first backend AI contract is stored in
`backend/app/prompts/design_graph.py`.

It defines the system prompt that instructs the model to return a practical,
buildable design graph in JSON only. The API exposes this contract at
`GET /prompts/design-graph` so the frontend or orchestration layer can consume
one shared version.
