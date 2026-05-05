#!/usr/bin/env node
/* KATHA AI — mock backend
 * =======================
 * Zero-install Node.js HTTP server that mimics the FastAPI backend
 * endpoints the frontend expects, just enough to make the /chat and
 * /design surfaces functional end-to-end during development.
 *
 * Why a mock?
 *   The real Python backend needs Postgres + pgvector + Redis + an
 *   Anthropic / OpenAI API key + alembic migrations applied. Setting
 *   that up is ~30-60 min. This mock unblocks the frontend instantly
 *   so we can verify SSE plumbing, payload shape, and UX flow before
 *   any of that work lands.
 *
 * Endpoints implemented:
 *   - POST /api/v1/chat/stream
 *       Streams realistic SSE token-by-token responses based on the
 *       requested mode (quick / deep / auto). Final event is "done"
 *       with suggestions + reference_links.
 *
 *   - POST /api/v1/projects/:id/generate           (stub for MVP 2)
 *       Returns a fake design graph + estimate after a short delay.
 *
 *   - GET  /api/v1/health
 *       Liveness probe — returns {"status":"ok","mock":true}.
 *
 * Usage:
 *   node scripts/mock-backend.mjs            # default port 8000
 *   PORT=8001 node scripts/mock-backend.mjs  # override
 *
 * Swap to real backend:
 *   1. Stop this server (Ctrl+C)
 *   2. cd backend && uvicorn app.main:app --reload --port 8000
 *   (See docs/data/backend-wiring.md for full setup)
 */

import http from "node:http";

const PORT = Number.parseInt(process.env.PORT || "8000", 10);

// ─────────────────────────────────────────────────────────────────────
// CORS
// ─────────────────────────────────────────────────────────────────────

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400",
};

// ─────────────────────────────────────────────────────────────────────
// Canned chat responses by mode
// ─────────────────────────────────────────────────────────────────────

const RESPONSE_BANK = {
  quick: (prompt) => ({
    body: `**Short answer:** ${quickAnswerFor(prompt)}\n\nKATHA mock response — quick mode is set to a 3–5 line cap by design.`,
    suggestions: [
      "Show me the working drawing for this",
      "What does NBC say about it?",
      "Compare two materials for this",
    ],
  }),
  deep: (prompt) => ({
    body: deepAnswerFor(prompt),
    suggestions: [
      "Generate a render of this concept",
      "Pull the cost estimate",
      "Show me NBC §4.2 verbatim",
      "Suggest 3 material alternates",
    ],
    reference_links: [
      {
        title: "NBC-2016 Part 3 §4.2.1 — door widths",
        url: "https://bis.gov.in/nbc-2016",
        type: "standard",
      },
      {
        title: "ECBC envelope U-value targets",
        url: "https://beeindia.gov.in/ecbc",
        type: "standard",
      },
      {
        title: "Manufacturing Handbook §6 — joinery tolerances",
        url: "https://example.com/mfg-handbook",
        type: "documentation",
      },
    ],
  }),
  auto: (prompt) =>
    prompt.length > 60 ? RESPONSE_BANK.deep(prompt) : RESPONSE_BANK.quick(prompt),
};

function quickAnswerFor(prompt) {
  const p = prompt.toLowerCase();
  if (p.includes("door") || p.includes("nbc"))
    return "NBC-2016 Part 3 specifies a **1000mm** entry door minimum, **800–900mm** interior. Bathrooms accept **750mm**.";
  if (p.includes("walnut") || p.includes("teak"))
    return "**Walnut** has tighter grain and warmer tone (mid-century classic); **teak** is more durable outdoors and tighter on cost (~₹450/kg vs ₹560/kg).";
  if (p.includes("kitchen"))
    return "Contemporary 3 BHK kitchen: **2.5m working width minimum**, island spacing **1100mm**, counter height **850–900mm**.";
  if (p.includes("ecbc") || p.includes("envelope"))
    return "**ECBC warm-humid:** wall U-value ≤ **0.40 W/m²K**, roof ≤ **0.33**, WWR ≤ **0.40**. Mumbai falls in this zone.";
  return "Mock quick response. The real KATHA agent would answer with cited values from NBC, ECBC, and the live-feeds layer.";
}

function deepAnswerFor(prompt) {
  return `## Concept

${prompt.length > 0 ? `Considering your brief — "${prompt.slice(0, 120)}${prompt.length > 120 ? "…" : ""}" — KATHA recommends a ` : "We recommend a "}**theme-led, code-grounded approach** anchored in BRD §1A.

## Key dimensions (NBC-aligned)

| Element | Spec | Source |
|---|---|---|
| Door (entry) | 1000mm × 2100mm | NBC Part 3 §4.2.1 |
| Door (interior) | 800–900mm | NBC Part 3 §4.2.1 |
| Corridor (residential) | ≥ 800mm | NBC Part 3 §3.1 |
| Ceiling | ≥ 2.75m | NBC Part 3 §2.1 |
| Stair tread / rise | 250mm / 190mm | NBC Part 4 §3.2 |

## Materials & cost (live MCX)

- **Mild steel** ₹62/kg (live, captured 3 hrs ago)
- **Walnut** ₹560/kg (theme-default for mid-century)
- **Brass** ₹820/kg (accent — handles, hardware)

## Process diagram

\`\`\`
brief → knowledge layer (RAG-grounded) → design graph
                                       → cost engine (live)
                                       → render pipeline (Nano Banana Pro)
                                       → spec sheets + BOQ
\`\`\`

## Next steps

This is a **mock response** from the dev mock backend. The real KATHA agent would synthesize this from RAG over NBC PDFs, pull live MCX prices, generate the actual design graph, and return citations on every datum.

> Switch to the real backend (\`cd backend && uvicorn app.main:app --port 8000\`) when you're ready for the actual agent.`;
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    ...CORS_HEADERS,
  });
  res.end(JSON.stringify(payload));
}

function sse(res, event) {
  res.write(`data: ${JSON.stringify(event)}\n\n`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Tokenize a string into chunks the way an LLM streams — words +
// occasional whitespace, with a soft chunking on markdown structure
// so it FEELS like a real model.
function tokenizeForStream(text) {
  // Split into roughly word-sized chunks, keeping line breaks intact.
  const tokens = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const parts = line.split(/(\s+)/).filter(Boolean);
    for (const p of parts) tokens.push(p);
    if (i < lines.length - 1) tokens.push("\n");
  }
  return tokens;
}

// ─────────────────────────────────────────────────────────────────────
// Endpoint handlers
// ─────────────────────────────────────────────────────────────────────

async function handleChatStream(req, res) {
  let body;
  try {
    body = await readJsonBody(req);
  } catch (e) {
    return sendJson(res, 400, { error: "invalid_json", message: String(e) });
  }
  const message = (body.message || "").trim();
  const mode = (body.mode || "auto").toLowerCase();
  const responder = RESPONSE_BANK[mode] ?? RESPONSE_BANK.auto;
  const { body: text, suggestions, reference_links } = responder(message);

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
    ...CORS_HEADERS,
  });

  // Stream tokens with a small jitter per token so it feels like real
  // generation. ~30-90ms per token (faster on whitespace).
  const tokens = tokenizeForStream(text);
  let aborted = false;
  req.on("close", () => (aborted = true));

  for (const tok of tokens) {
    if (aborted) return;
    sse(res, { type: "token", content: tok });
    const wait = /\s/.test(tok) ? 8 + Math.random() * 14 : 30 + Math.random() * 70;
    await sleep(wait);
  }

  if (aborted) return;
  sse(res, {
    type: "done",
    content: text,
    suggestions: suggestions ?? [],
    image_prompt: null,
    video_query: null,
    youtube_query: null,
    research_query: null,
    reference_links: reference_links ?? [],
    mode,
  });
  res.end();
}

async function handleProjectGenerate(req, res, projectId) {
  let body;
  try {
    body = await readJsonBody(req);
  } catch (e) {
    return sendJson(res, 400, { error: "invalid_json", message: String(e) });
  }
  await sleep(800);
  sendJson(res, 200, {
    project_id: projectId,
    version: 1,
    status: "ok",
    graph_data: {
      room: {
        type: body.room_type ?? "study",
        dimensions: body.dimensions ?? { length: 4, width: 3, height: 3 },
      },
      objects: [
        {
          id: "obj_table",
          type: "table",
          name: "Walnut Table",
          dimensions: { length: 1.4, width: 0.6, height: 0.75 },
          material: "walnut",
        },
      ],
      style: {
        primary: body.style ?? "modern",
        signature_moves: ["Tapered legs", "Brass accents"],
      },
    },
    estimate: {
      status: "ready",
      currency: "INR",
      total_low: 142500,
      total_high: 195000,
      totals: { low: 142500, base: 168000, high: 195000 },
      line_items: [
        { category: "Material", item: "Walnut top", total: 38400 },
        { category: "Material", item: "Mild steel base", total: 1260 },
        { category: "Material", item: "Brass handles", total: 7800 },
        { category: "Labour", item: "Woodworking 18hr", total: 5400 },
      ],
    },
  });
}

// ─────────────────────────────────────────────────────────────────────
// Router
// ─────────────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  // CORS preflight.
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  if (req.method === "GET" && pathname === "/api/v1/health") {
    return sendJson(res, 200, { status: "ok", mock: true, port: PORT });
  }

  if (req.method === "POST" && pathname === "/api/v1/chat/stream") {
    return handleChatStream(req, res);
  }

  // /api/v1/projects/:id/generate
  const projectMatch = pathname.match(/^\/api\/v1\/projects\/([^/]+)\/generate$/);
  if (req.method === "POST" && projectMatch) {
    return handleProjectGenerate(req, res, projectMatch[1]);
  }

  sendJson(res, 404, {
    error: "not_found",
    message: `${req.method} ${pathname} not implemented in mock`,
    hint: "See scripts/mock-backend.mjs — only /api/v1/chat/stream and /api/v1/projects/:id/generate are stubbed.",
  });
});

server.listen(PORT, () => {
  /* eslint-disable no-console */
  console.log(`KATHA mock backend listening on http://localhost:${PORT}`);
  console.log("  POST /api/v1/chat/stream            — SSE token streaming");
  console.log("  POST /api/v1/projects/:id/generate  — stubbed design graph");
  console.log("  GET  /api/v1/health                 — liveness");
  console.log("");
  console.log("Stop with Ctrl+C. Swap for real backend: see docs/data/backend-wiring.md");
});
