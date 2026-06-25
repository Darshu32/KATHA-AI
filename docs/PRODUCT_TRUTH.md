# KATHA AI — Product Truth

> **Status:** Living document. Source of truth for what KATHA actually is.
> Built collaboratively in conversation on 2026-05-04. Reconciled against
> the shipped codebase on **2026-06-24**. Update in place as decisions
> evolve. Every subsequent design / implementation conversation references
> this doc to avoid drift.
>
> **Status legend (used throughout):**
> - ✅ **DONE** — built, wired, verified in code
> - 🟡 **PENDING** — decided in principle, not yet built / not yet wired end-to-end
> - 🔴 **NOT STARTED** — needed, no code yet
> - ⏭️ **DEFERRED** — intentionally parked (Phase 2 / post-MVP / trigger-based)
>
> For the consolidated "what's left" view, jump to **§8**.

---

## 0. Top-level shape

KATHA AI is a self-serve product (no admin role, no ops team) that
delivers two distinct experiences inside one product:

1. **Chat context window** (`/chat`) — knowledge / discussion / planning
2. **Image generation context window** (`/design`) — visual generation

✅ **RESOLVED (was open):** The two windows are **separate routes**
(`/chat` and `/design`), not side-by-side panels or a dual-app shell.
Mobile ships `/chat` only; `/design` is desktop-only.

---

## 1. MVP 1 — Chat context window

### 1.1 Purpose

The chat agent delivers architecture-domain knowledge: concepts, reference
diagrams, notes, YouTube links, "what to do next" suggestions. Same shape
as a general AI agent (ChatGPT / Claude / Perplexity), but specialised
for architectural / interior / product-design knowledge.

### 1.2 Three chat modes — ✅ DONE (UI + mode-aware backend)

| Mode | Response shape | Diagrams | Use case |
|---|---|---|---|
| **Quick** | Short, intense, dense-knowledge answer | Optional | Fast lookup ("what is the door width for residential entry?") |
| **Deep** | Continuous multi-turn discussion. Suggests **present + future** considerations. Diagrams expected in Deep | Required | Real design conversations, planning sessions |
| **Auto** | Default / adaptive — picks Quick or Deep style based on context | Adaptive | When the user doesn't want to choose |

✅ Mode selector is wired in the chat UI; backend is mode-aware and the
mock backend honours `mode` in `RESPONSE_BANK`.

### 1.3 Response content

Every response (mode-dependent) can include:
- Knowledge body (architecture concepts, codes, materials, ergonomics, etc.)
- Reference diagrams
- Notes
- YouTube links
- Next-step suggestions ("you might want to consider …")

✅ The `done` SSE event carries `suggestions`, `reference_links`,
`image_prompt`, `video_query`, `youtube_query`, `research_query` — the UI
renders suggestions + reference links today.

### 1.4 Dynamic-ness

**No hardcoded knowledge** — responses are generated dynamically through
the LLM + RAG + live sources.

✅ **RESOLVED:** Stage 15 externalised the Tier 2/3 Python-literal
knowledge layer into versioned DB rows (`building_standards`, etc.) with a
literal fallback. The "kill hardcoded knowledge" decision has landed.

### 1.5 Notes feature — ✅ DONE (auto-author + persist)

- **Right sidebar** in the chat window
- Applicable in **Deep mode**
- **Auto-generated** — the system writes notes as the conversation
  progresses (`parseDeepModeToNotes`), summarising what's discussed
- **Persisted** per session (`useNotesPersist`)
- **Format:** structured markdown matching the shape of this doc
  (sections, status badges, tables, bullets, code blocks, changelog),
  rendered live as the conversation progresses

✅ **RESOLVED (2026-06-25):** user-editable-in-place is fully wired —
`note-block.tsx` (contentEditable blocks), `add-block-menu.tsx`,
`note-section-header.tsx`, `note-section-tags.tsx`, backed by
`useNotesStore` (`updateBlock`/`addBlock`/`deleteBlock`) with debounced
sync (`use-notes-persist.ts`) to a real backend (`routes/notes.py`:
GET/PUT/DELETE `/sections`, POST `/import`). Export is wired too —
`notes-export.ts` (`notebookToMarkdown` → `.md` download; `notebookToHTML`
→ jspdf `.pdf`), plus per-section copy-as-markdown.

---

## 1.6 Clarifications — status

| # | Question | Status |
|---|---|---|
| 1 | Two-window UX layout | ✅ **RESOLVED** — separate routes `/chat` + `/design` |
| 2 | Quick-mode length | ✅ Capped to a short answer (mock: 3–5 lines); real cap tuned in agent prompt |
| 3 | Deep-mode mandatory diagram | ✅ **Hard-gated (2026-06-25)** — `chat_engine.stream_chat_response` synthesizes a fallback `image_prompt` when the LLM omits one in Deep mode, so every Deep response carries a diagram; mock backend mirrors this |
| 4 | Auto-mode trigger | ✅ Adaptive on context (mock heuristic: prompt length; real = agent decides) |
| 5 | Reference-diagram source | ✅ Generated (LLM-backed diagram services + deterministic registry) |
| 6 | YouTube links source | ✅ **Fully built** — real `search_youtube()` → YouTube Data API, `/chat/search-youtube` route, `YouTubeReferences` cards. ⚠️ **Ops gap only:** `YOUTUBE_API_KEY` unset → gracefully returns `[]` |
| 7 | Notes — when generated / persisted | ✅ Live + persisted per session |
| 8 | Notes — editable / exportable | ✅ Auto-authored + persisted + inline-editable + `.md`/`.pdf` export (verified 2026-06-25) |

---

## 2. MVP 2 — Image Generation Context Window (`/design`)

> *"The massive thing in our project."* The design-generation surface where
> prompts become drawings, models, specs, and live cost.

### 2.1 Purpose

The agent generates complete design output across multiple disciplines
and dimensionalities, driven by the user prompt + design context.

### 2.2 What the agent generates

Across **four design scopes**: architecture · interior · furniture · product.

In **three dimensionalities**:
- **2D** sketches (plans, elevations, sections) — ✅ services exist
- **3D** sketches / models / renders — 🟡 mesh provider not integrated
- **4D** sketches (time-based) — ⏭️ deferred (Veo)

### 2.3 Theme system — ✅ DONE

- User picks the theme; theme drives material palette, proportions, style.
- Catalogue locked to **Pedestal / Mid-Century Modern / Contemporary /
  Modern / Custom**. Theme resolves from `graph_data.style.primary`.

### 2.4 Import (user → KATHA) — ✅ DONE (15 importers)

PDF · DOCX · XLSX · CSV · DXF · OBJ · STEP · image · text (+ others).
Revit interop is via IFC import/export (native `.rvt` is a Phase 2 trigger
candidate — see §8).

### 2.5 Export / output (KATHA → user) — ✅ DONE

- **Working drawings (5):** plan · elevation · section · isometric · detail
  — ✅ all five now wired in the Views tab (Option A, 2026-06-24).
- **Conceptual diagrams (8):** concept transparency · form development ·
  massing · volumetric · design process · solid/void · spatial organism ·
  hierarchy — ✅ served by the deterministic registry
  (`app/services/diagrams/`). Frontend catalogue corrected 2026-06-24 to
  mirror the registry (collapsed the two volumetric cards to one).
- **Spec sheets (4):** material · manufacturing · MEP · cost — ✅
- **Export formats (17 exporters):** PDF · DOCX · XLSX · PPTX · HTML ·
  DXF · OBJ · GLTF · FBX · IFC · STEP · IGES · gcode · cam_prep ·
  GeoJSON (+ synthesis) — ✅ ExportModal wired to `/export/formats`.

### 2.6 Dynamic cost estimation — ✅ DONE

- Cost engine runs against the current design state; pulls Stage 1 +
  Stage 12 live feeds.
- Displayed in the terminal **Cost** tab.
- ✅ **RESOLVED (verified 2026-06-25):** recalc fires on **every** design
  change — `generate`, `edit`, and `theme-switch` all recompute
  `estimate` + `mep_cost_estimate` server-side and return them; CostTab
  re-renders reactively. There is no manual "recalculate" button; cost is
  bound to each design action. (Only the unused stub
  `updatePosition`/`updateMaterial` endpoints don't recalc — they aren't
  wired into the workspace.)

### 2.7 UI layout — ✅ DONE (shipped shape differs from original sketch)

Shipped `/design`:
- **Left sidebar:** accordion — Brief / Space / Requirements / Regulatory.
- **Canvas:** renders, drawings, diagrams (click-to-swap).
- **Right sidebar:** 6-tab shell — **Summary · Views · Specs · Cost ·
  Checks · Recs**.
- **Terminal (bottom):** **Cost · Problems · Generation Log · Citations**
  tabs.

✅ **RESOLVED (2026-06-25):** the original §2.9 four-tab terminal is now
complete. **Generation Log** renders a deterministic record of the latest
generation's pipeline steps (graph resolved → theme → render → estimate →
MEP → validation), derived from the response (generate is one request, not
a streaming feed, so this is honest summary, not faked tokens).
**Citations** aggregates every source-tagged datum the design draws on —
code-compliance rows, validation issues with `source_section`/`reference`,
and the MEP cost jurisdiction band — over data the response already
carries (no new backend call).

### 2.8 Answered clarifications

1. ✅ **Chat → Image-gen handoff.** On a "let's design this" trigger the
   chat brief flows to `/design` via `seedFromBrief` / `seededFromBriefId`.

2. ⚠️ **User editing — DECISION CHANGED.** Original doc scoped editing to
   import/export only. **Reality: object-level in-canvas editing is now
   wired** via `ObjectsPanel` → `POST /projects/{id}/edit`. The user can
   edit objects directly, not only on import/export.

3. 🟡 **Real-time vs button-driven.** Button/generate-driven today.

4. ✅ **Left sidebar contents.** Brief / Space / Requirements / Regulatory.

5. ✅ **Right sidebar contents.** Summary / Views / Specs / Cost / Checks / Recs.

6. ✅ **Theme catalogue.** BRD §2A list (Pedestal / MCM / Contemporary /
   Modern / Custom).

7. ✅ **Design scope picker.** Agent infers scope from prompt, override pill.

8. 🟡 **Error model.** Terminal Problems tab shipped; full 4-class model
   (§2.9) partially realised.

### 2.9 Error / problems model — 🟡 PARTIAL

Terminal panel doubles as a Problems pane. Four issue classes proposed:

| Class | Trigger | Severity | Status |
|---|---|---|---|
| 🔴 **Hard error** | System / API failed | Blocking | 🟡 envelope exists (Stage 13) |
| 🟡 **Validation warning** | Violates known rule (code / ergonomic / structural) | Non-blocking | ✅ Checks tab |
| 🔵 **Suggestion / advisory** | Recommendations engine | Info | ✅ Recs tab |
| 🟢 **Provenance / confidence** | Stage 11 transparency banner | Info | 🟡 partial |

Terminal tabs shipped: **Cost · Problems · Generation Log · Citations**
(all four originally specced, completed 2026-06-25).

Built on existing infra: Stage 11 confidence/provenance · Stage 13 error
envelope · Stage 12 freshness · Stage 6 RAG citations · Stage 4 tool audit.

---

## 3. Phase 2 — Haptic Interface ⏭️ DEFERRED (data layer ✅ DONE)

Per BRD Layer 7. **Phase 1 ships the haptic-ready data structure** —
✅ DONE: `app/haptic/` (catalog + exporter + validator + 6 tables, alembic
0020) and `app/agents/tools/haptic.py`. The JSON payload is end-to-end
production (`build_haptic_payload()`).

**Phase 2 = hardware integration (⏭️ parked):**
- Order haptic arm hardware (UR3 ~$23K or custom)
- Build haptic driver / middleware (signature patterns → motion profiles)
- Material haptic library validation against physical samples
- Client haptic session workflow
- First paid haptic session

(Per BRD: Aug–Sep 2026.) **Note (2026-06-24):** founder direction — only a
*hint/teaser* of haptic for now; full haptic work is parked until after the
landing page ships. See §8.

---

## 4. Provider stack — 🟡 decision vs. code reality

**Memory decision (region-routed via provider abstraction):**
Azure OpenAI (chat) · Vertex AI Gemini (image) · Meshy v1 → self-host (3D)
· Veo 3 (4D, deferred).

**Code reality today:**

| Layer | Decided (memory) | In code now | Status |
|---|---|---|---|
| Chat / agent | Azure OpenAI | Direct OpenAI (gpt-4o); Anthropic dormant | 🟡 not yet region-routed to Azure |
| Image gen | Vertex Gemini | Direct Gemini + stub at `app/workers/tasks.py` | 🟡 provider abstraction in place, integration deferred |
| 3D mesh | Meshy v1 → self-host | not integrated | 🔴 |
| Video / 4D | Veo 3 | none | ⏭️ deferred |
| Embeddings | — | OpenAI `text-embedding-3-small` | ✅ |
| RAG corpus | pgvector | pgvector | ✅ |
| YouTube link feed | — | `youtube_query` plumbed, no API call | 🔴 |

---

## 5. Frontend / hosting

| Item | Status |
|---|---|
| Frontend stack | ✅ Next.js 15 / React 19 / Tailwind / Zustand — wired to backend via `lib/api-client.ts` |
| Design language | ✅ "architect's drafting" register (pencil-red `#C8362D`, ink/paper neutrals, mono numerics) |
| Landing page | 🔴 **NOT STARTED** — next focus |
| Hosting / deployment | 🟡 EU-hosted v1 planned (GDPR + DPDPA); not yet provisioned |
| Pricing model | 🔴 undecided |
| Target market | Universal OS for architects worldwide (Indian co.). 8 regions, TAM ≈ 1.44M. v1 = EU-hosted backend + EU-routed AI. |

---

## 6. Codebase reality — current state (2026-06-24)

- ✅ FastAPI backend — **28 routers**
- ✅ **17 exporters**, **15 importers**
- ✅ 8-id deterministic diagram registry + 9 LLM-backed diagram services
- ✅ 5 working-drawing services (plan/elevation/section/isometric/detail) —
  all wired into the Views tab
- ✅ 4 spec services (material/manufacturing/MEP/cost)
- ✅ Stage 6 RAG + pgvector; Stage 12 live feeds (MCX/FX/GST/vendors)
- ✅ Stages 1–15 backend (pricing, knowledge, tools, memory, vision,
  haptic data layer, transparency, polish, Tier 2/3 DB externalisation,
  Massing diagram)
- ✅ Frontend wired: `/chat` (3 modes + auto-notes) and `/design`
  (left accordion + 6-tab right rail + terminal)
- ✅ Object-level in-canvas editing via `ObjectsPanel` → `/projects/{id}/edit`
- ✅ ExportModal → `/export/formats`; VersionTimeline chips
- 🟡 Image generation provider integration still stubbed
  (`app/workers/tasks.py`) — no real mesh/render provider
- 🟡 Mock backend (`scripts/mock-backend.mjs`) only stubs `/chat/stream`
  + `/projects/:id/generate`; everything else 404s. Real backend needs
  Postgres + pgvector + Redis + API keys + alembic.

---

## 7. What I will stop doing

- Will not propose new stages / features until each MVP is locked here.
- Will not assume admin / ops users exist.
- Will not assume the BRD overrides founder's product vision in conversation.
- Will not jump to architecture before requirements are written.

---

## 8. Remaining work — consolidated checklist

**Near-term (founder's stated order):**
1. 🔴 **Landing page** — next focus, not started.
2. ⏭️ **Haptic teaser/badge** — a *hint* only on the product surface;
   full haptic parked until after the landing page.

**MVP polish / wiring:**
3. 🟡 **API keys + real backend run** — wire OpenAI / (Azure) / Vertex /
   MCX feed keys; run a real architectural project end-to-end; hand to a
   beta architect (testing-only, not commercial).
4. 🟡 **Engine-tool wiring audit** — verify every UI surface fires the
   right backend agent tool; end-to-end test.
5. 🟡 **Image-gen provider** — replace `app/workers/tasks.py` stub with
   real render/mesh integration (Vertex Gemini image; Meshy for 3D).
6. ✅ **Notes** — user-editable-in-place + `.md`/`.pdf` export — **DONE**
   (verified 2026-06-25; was mis-flagged as pending).
7. ✅ **Terminal tabs** — **Generation Log** + **Citations** added — **DONE**
   (2026-06-25). Terminal now Cost · Problems · Generation Log · Citations.
8. ✅ **Live cost refresh** — already continuous (recomputes on
   generate/edit/theme-switch) — **DONE** (verified 2026-06-25; was
   mis-flagged as pending).
9. ✅ **YouTube link feature** — fully built end-to-end — **DONE** (verified
   2026-06-25). ⚠️ Only remaining step is an **ops** task: set
   `YOUTUBE_API_KEY` in `.env` (no code change).
10. ✅ **Deep-mode mandatory-diagram enforcement** — hard-gated in
    `chat_engine` (fallback `image_prompt`) + mock — **DONE** (2026-06-25).

**Provider / infra:**
11. 🟡 **Region-routed provider abstraction** — switch chat to Azure
    OpenAI; confirm Vertex routing; EU hosting v1.
12. ⏭️ **4D / video (Veo)** — deferred to post-MVP.

**Deferred / trigger-based (do NOT build speculatively):**
13. ⏭️ Native `.rvt` export — when a customer requires native Revit files.
14. ⏭️ Machine-specific G-code post-processors — when a mfg partner signs.
15. ⏭️ Strict-mode haptic export — when a hardware vendor requests it.
16. ⏭️ Semantic recall over chat turns — on long-session UX pain.
17. 🟡 **GDPR profile-delete agent tool** — before EU rollout closes.

**EU launch (legal, not code):**
18. 🟡 EU Representative appointment — parked; revisit before EU traffic.

---

## Changelog

- **2026-05-04** — Doc created. MVP 1, MVP 2, Phase 2 (haptic), provider
  stack deferred. Notes structure confirmed. MVP 2 clarifications captured.
- **2026-06-24** — **Reconciled against shipped codebase.** Added status
  legend. Flipped resolved items: two-window UX (separate routes), no-
  hardcoded-knowledge (Stage 15), notes auto-author+persist, theme system,
  importers/exporters, working drawings (all 5 wired), diagram registry,
  cost engine, left/right sidebar contents. Corrected stale counts (28
  routers, 17 exporters, 15 importers). **Flagged decision change:** object-
  level in-canvas editing is now wired (was scoped to import/export only).
  Updated provider-stack section to show memory decision vs. code reality
  (direct OpenAI/Gemini today; Azure/Vertex/Meshy/Veo target). Added §8
  consolidated remaining-work checklist; flagged landing page (next) +
  haptic teaser (parked).
- **2026-06-25** — Verified the "notes polish" gap against code: it was
  already fully built (inline editing via `note-block.tsx` + store +
  backend `routes/notes.py`; `.md`/`.pdf` export via `notes-export.ts`).
  Corrected §1.5, §1.6 q8, and §8 item 6 from 🟡 to ✅.
- **2026-06-25** — Swept the five "polish gaps." Verified two were already
  done (live cost recalc on every action; YouTube fully wired bar the API
  key — an ops gap). **Built** the other two: (1) Deep-mode mandatory
  diagram now hard-gated via a fallback `image_prompt` in
  `chat_engine.stream_chat_response` (+ mock mirror); (2) terminal
  **Generation Log** + **Citations** tabs added to
  `image-workspace-mvp2.tsx`, sourced from data the generation response
  already carries. Updated §1.2, §1.6 q3/q6, §2.6, §2.7, §2.9, §8 (items
  7–10 → ✅).
