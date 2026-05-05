# KATHA AI — Product Truth

> **Status:** Living document. Source of truth for what KATHA actually is.
> Built collaboratively in conversation on 2026-05-04. Update in place as
> decisions evolve. Every subsequent design / implementation conversation
> references this doc to avoid drift.
>
> Sections marked **🟡 PENDING INPUT** are awaiting confirmation from the
> founder. Sections marked **✅ CONFIRMED** are locked unless explicitly
> revised here.

---

## 0. Top-level shape

KATHA AI is a self-serve product (no admin role, no ops team) that
delivers two distinct experiences inside one product:

1. **Chat context window** — knowledge / discussion / planning
2. **Image generation context window** — visual generation

The two windows are separate context surfaces (UX still being clarified —
side-by-side panels vs. switchable workspaces vs. two apps in one shell).

---

## 1. MVP 1 — Chat context window ✅ CAPTURED FROM CONVERSATION

### 1.1 Purpose

The chat agent delivers architecture-domain knowledge: concepts, reference
diagrams, notes, YouTube links, "what to do next" suggestions. Same shape
as a general AI agent (ChatGPT / Claude / Perplexity), but specialised
for architectural / interior / product-design knowledge.

### 1.2 Three chat modes

| Mode | Response shape | Diagrams | Use case |
|---|---|---|---|
| **Quick** | Short, intense, dense-knowledge answer | Optional | Fast lookup ("what is the BRD door width for residential entry?") |
| **Deep** | Continuous multi-turn discussion. Suggests **present + future** considerations. **Diagrams MANDATORY** in every Deep session | Required (every Deep response includes a diagram) | Real design conversations, planning sessions |
| **Auto** | Default / adaptive. Behaves as the name suggests — picks Quick or Deep style based on context | Adaptive | When the user doesn't want to choose |

### 1.3 Response content

Every response (mode-dependent) can include:
- Knowledge body (architecture concepts, codes, materials, ergonomics, etc.)
- Reference diagrams
- Notes
- YouTube links
- Next-step suggestions ("you might want to consider …")

### 1.4 Dynamic-ness

**No hardcoded knowledge** — responses are generated dynamically through
the LLM + RAG + image-gen API keys. (This is the architectural decision
already made: kill the Python-literal knowledge layer, replace with
LLM + RAG + live sources.)

### 1.5 Notes feature

- **Right sidebar** in the chat window
- Applicable **only in Deep mode** (not Quick, possibly auto)
- **Auto-generated** — the system writes notes as the conversation
  progresses, summarising what's been discussed
- **Format / styling: same shape as this `PRODUCT_TRUTH.md` document.**
  The notes sidebar renders structured markdown with:
  - Hierarchical sections / subsections (`##`, `###`)
  - Status badges (✅ confirmed, 🟡 pending, ⚠️ caveat, 🔴 blocker, etc.)
  - Tables for comparisons / decisions
  - Bullet lists for points / next steps
  - Code blocks for snippets / values when relevant
  - Inline links (sources, references)
  - A "Changelog" or "Updated" timestamp footer
- Updated **live** as the conversation progresses — when a new topic
  enters the chat, a new section appears; when a decision is reached,
  its status flips from 🟡 to ✅; when something's flagged as TBD it
  stays 🟡 until resolved.
- (Open: user-editable in place? export to .md? scoped per session vs.
  per project?)

---

## 1.6 🟡 PENDING INPUT — clarifications needed before MVP 1 is fully locked

A few specifics I need confirmed so the build matches the vision:

1. **Two context windows — UX layout.** Side-by-side panels in one
   workspace? Switchable tabs? Two separate routes? The frontend
   architecture depends on this.

2. **Quick mode response length.** What's "short, intense"?
   - One sentence?
   - One paragraph (~3 sentences)?
   - Token cap (e.g. ≤ 200 tokens)?
   - User-editable cap?

3. **Deep mode "mandatory diagram".** Every single response in a Deep
   session generates a diagram? Or one diagram per session at a
   meaningful moment? What kind of diagram —
   architectural sketches, flowcharts, ergonomic diagrams, conceptual?

4. **Auto mode trigger.** What does "adapt" mean — picks Quick or Deep
   based on question complexity? User can override per-message?

5. **Reference diagrams source.** Are these:
   (a) **retrieved** from a RAG corpus of existing diagrams, or
   (b) **generated** fresh by Nano Banana Pro / similar each time?

6. **YouTube links source.** Real-time YouTube Search API call (need
   YouTube Data API key)? Or curated set per topic? Or RAG over
   pre-ingested transcript corpus?

7. **Notes — when generated.** Now confirmed: **live**, updated as the
   conversation progresses (matches the way this doc is being written).
   Confirm: stored persistently per chat session? Per user account?
   Both?

8. **Notes — format.** Now confirmed: structured markdown matching
   the shape of `PRODUCT_TRUTH.md` (sections, tables, status badges,
   bullets, code blocks, changelog). Confirm: user-editable in place
   (click a section to revise)? Export-to-`.md`/`.pdf` button?

---

## 2. MVP 2 — Image Generation Context Window ✅ CAPTURED FROM CONVERSATION

> *"The massive thing in our project."* This is the centrepiece —
> the design-generation surface where prompts become drawings,
> models, specs, and live cost.

### 2.1 Purpose

The agent generates complete design output across multiple disciplines
and dimensionalities, all driven by the user prompt. Output is highly
productive — meaning fast iteration cycles and rich, complete deliverables
per generation.

### 2.2 What the agent generates

Across **four design scopes**:

- Architecture design
- Interior design
- Furniture design
- Product design

In **three dimensionalities**:

- **2D** sketches (plans, elevations, sections)
- **3D** sketches / models / renders
- **4D** sketches (time-based — walkthroughs, animations, construction sequence)

All generation is driven by the user prompt + design context.

### 2.3 Theme system

- User picks the theme
- Theme drives material palette, proportions, style, etc.
- (Open: same theme catalogue as the chat MVP — Pedestal / MCM /
  Contemporary / Modern / Custom — or different? See §2.8 q1)

### 2.4 Import (user → KATHA)

The user can bring existing artefacts into the workspace:

- **Revit** (heavily emphasised — first-class import)
- CAD files (DWG / DXF / STEP / IGES)
- 3D models (OBJ / FBX / GLTF)
- Site plans
- Design briefs

These ground the generation — KATHA reads existing geometry, dims, and
constraints rather than starting from scratch.

### 2.5 Export / output (KATHA → user)

Per the BRD, every generation produces:

- Working drawings (plan / elevation / section / detail / isometric)
- 8 conceptual diagrams (concept transparency, form, massing,
  volumetric, design process, solid/void, spatial organism, hierarchy)
- Material specifications
- Manufacturing specifications
- MEP specifications (when architectural)
- All export formats from BRD §5A — PDF, DOCX, XLSX, PPTX, HTML,
  DWG/DXF, IFC (Revit interop), STEP/IGES, OBJ/FBX/GLTF, G-code,
  CAM prep, GeoJSON

### 2.6 Dynamic cost estimation

- Cost engine runs **live** against the current design state
- Every change (material swap, dim tweak, theme change) → cost recalculates
- Pulls from current pricing layer (Stage 1 + Stage 12 live feeds)
- Output displayed in the dedicated **terminal panel** (see §2.7)

### 2.7 UI layout

```
┌──────────────┬─────────────────────────────────┬──────────────┐
│              │                                 │              │
│   LEFT       │   IMAGE CONTEXT WINDOW          │   RIGHT      │
│   SIDEBAR    │   (the canvas — design renders, │   SIDEBAR    │
│              │    drawings, 3D viewer)         │              │
│              │                                 │              │
│              │                                 │              │
│              │                                 │              │
├──────────────┴─────────────────────────────────┴──────────────┤
│   TERMINAL  —  live cost estimation panel                     │
│   (numbers update as the design changes; like a code-editor   │
│    terminal but for the cost engine)                          │
└───────────────────────────────────────────────────────────────┘
```

(Open: what specifically lives in left sidebar vs right sidebar — see
§2.8 q4.)

### 2.8 Answered clarifications

1. ✅ **Chat → Image-gen handoff.** When the user says *"let's design
   this"* in the chat (or similar trigger), the system **switches to
   the image-gen workspace and generates based on the discussion that
   already happened in chat**. Context flows: chat brief, discussion,
   auto-notes → image-gen seed.

2. ✅ **User editing.** Editing the design happens **only when
   content is imported / exported** — i.e., the user touches the design
   when they hand a file in (Revit / CAD / 3D model) or take one out.
   In-canvas direct editing during normal generation is NOT in scope
   for MVP 2; user iterates by re-prompting / re-generating.

3. 🟡 **Real-time vs button-driven.** Not specified yet. To revisit.

4. 🟡 **Left sidebar contents.** Founder will share shortly.

5. 🟡 **Right sidebar contents.** Founder will share shortly.

6. ✅ **Theme catalogue.** Keep BRD §2A list for now —
   **Pedestal / Mid-Century Modern / Contemporary / Modern / Custom**.
   May expand later.

7. ✅ **Design scope picker.** Founder said "anything is fine" — so
   default behaviour: **agent infers scope from the prompt**
   (architecture / interior / furniture / product), with an optional
   pill in the UI to override. Sensible default; revisit if real users
   complain.

8. 🟡 **Error model — see §2.9 below.** Founder asked: *"how will
   errors be created when the agent generates the design?"* — proposed
   model captured in §2.9 for confirmation.

### 2.9 Error / problems model — 🟡 PROPOSED

> Founder asked how errors surface during agent generation. Proposed
> answer below — confirm / revise.

The **terminal panel at the bottom** of MVP 2 doubles as a VS-Code-style
"Problems" panel. It surfaces four classes of issue, each with its own
visual treatment, so the user can scan severity at a glance.

| Class | Trigger | Severity | Example | UX |
|---|---|---|---|---|
| 🔴 **Hard error** | System / API failed (Nano Banana down, tool crashed, malformed output) | Blocking | "Image generation failed — provider returned 500. Retry?" | Red row + retry button + technical details on click |
| 🟡 **Validation warning** | Generation violates a known rule (BRD code, ergonomic range, structural limit) | Non-blocking | "Door width 720 mm < NBC minimum 800 mm" | Yellow row + cite the source rule + jump-to-element |
| 🔵 **Suggestion / advisory** | Agent's recommendations engine flags a non-error opportunity | Info | "Consider walnut over oak for this theme — more authentic to mid-century" | Blue row + accept / dismiss / explain |
| 🟢 **Provenance / confidence** | Stage 11 transparency banner attaches to every datum | Info | "Material price = MCX live, captured 2 hrs ago" / "Cost confidence: HIGH" | Green badge on element; click for full citation chain |

The terminal panel itself is **multi-tab**, like a code-editor terminal:

```
┌──────────────────────────────────────────────────────────────┐
│ Cost  │ Problems (3) │ Generation Log │ Citations            │
├──────────────────────────────────────────────────────────────┤
│ ₹ 1,42,500 (low)  ₹ 1,68,000 (base)  ₹ 1,95,000 (high)       │
│ ↓ updated as design changes                                  │
└──────────────────────────────────────────────────────────────┘
```

- **Cost tab** — live ₹ low / base / high; updates on every design change
- **Problems tab** — counts + scrollable list of all 🔴 🟡 🔵 issues
- **Generation Log** — what the agent is doing right now (streaming,
  like a build log: *"Generating elevation view... Calling cost engine
  for walnut top... Resolving live MCX price... Done."*)
- **Citations tab** — every source the design draws on (RAG chunks,
  NBC clauses, MCX timestamps, prior architect decisions)

This gives the user **the same level of transparency as a code editor**:
nothing happens silently, every error is actionable, every datum is
traceable.

(Built on infrastructure we already have:
- Stage 11 confidence + provenance banner
- Stage 13 canonical error envelope + error codes
- Stage 12 freshness levels on prices
- Stage 6 RAG citations
- Stage 4 tool audit trail)

---

## 3. Phase 2 — Haptic Interface ✅ CAPTURED

Per BRD Layer 7. Phase 1 already ships the **haptic-ready data
structure** (Stage 9 — `app/haptic/`, `app/agents/tools/haptic.py`).

Phase 2 = hardware integration:
- Order haptic arm hardware (UR3 or custom)
- Build haptic driver / middleware
- Material haptic library mapping
- Client haptic session workflow
- First paid haptic session

(Per BRD: Aug–Sep 2026 timeline.)

---

---


## 4. Provider stack — 🟡 DEFERRED

Founder parked this decision (2026-05-04) — to be revisited after MVPs
are fully described. Captured options for when it comes back up:

| Layer | Options on the table | Status |
|---|---|---|
| Chat / agent reasoning | GPT-5.4 (founder initial pick) / Claude Sonnet 4.6 (codebase, benchmark winner for architectural reasoning) / Gemini 3 Pro (pairs with Nano Banana) | Deferred |
| Image generation | Nano Banana Pro (founder initial pick — solid choice, Veras-validated) | Deferred |
| Video / 4D | Veo 3.1 / Kling 3.0 / Seedance / Runway Gen-4 | Deferred |
| Embeddings | OpenAI `text-embedding-3-small` (current) / Voyage AI 3 (better retrieval) | Deferred |
| RAG corpus | pgvector | Confirmed |
| Web search (for YouTube link feature) | GPT-5.4 native / Brave / Tavily / YouTube Data API | Deferred |

**Cost reference** (Claude Sonnet 4.6 — the lowest-friction option since
codebase is wired):
- $3 / 1M input tokens, $15 / 1M output tokens
- 90% discount on cached input ($0.30 / 1M)
- Realistic monthly chat cost at 1k DAU: ~$2k/month with caching

---

## 5. Frontend / hosting — 🟡 PENDING INPUT

| Item | Status |
|---|---|
| Frontend stack (Next.js shell exists, not wired) | Pending — keep / replace? |
| Design language | Pending |
| Hosting / deployment | Pending |
| Pricing model (free / paid / enterprise) | Pending |
| Target market (India / global / specific city) | Pending |

---

## 6. Codebase reality — current state

What's wired today (to be confirmed against the founder's vision):

- ✅ FastAPI backend with 25 routers
- ✅ Anthropic Claude as primary agent runtime (may be replaced per §4)
- ✅ Stage 6 RAG corpus + pgvector
- ✅ Stage 12 live data feeds (MCX/FX/GST/vendors)
- ✅ Stages 1–14 backend (pricing, knowledge, tools, memory, vision, haptic, transparency, polish)
- ⚠️ Frontend Next.js shell present but not wired to backend
- ⚠️ Image generation stub at `app/workers/tasks.py:79` — no real provider integration yet
- ⚠️ Layer 1B/1C architectural knowledge currently hardcoded in
      `app/knowledge/*.py` Python literals (decision already made: replace
      with RAG + LLM + live sources)

---

## 7. What I will stop doing

(Founder explicitly asked to stop the miscommunication pattern.)

- Will not propose new stages / features until each MVP is locked in this doc.
- Will not assume admin / ops users exist.
- Will not assume the BRD is the source of truth where it conflicts with
  founder's product vision shared in conversation.
- Will not jump to architecture before requirements are written.

---

## Changelog

- **2026-05-04** — Doc created. Captured MVP 1 from conversation.
- **2026-05-04** — Notes feature: confirmed structure mirrors this doc's
  shape (hierarchical markdown + status badges + tables + bullets +
  changelog). Updated live as conversation progresses.
- **2026-05-04** — MVP 2 (Image Generation Context Window) captured.
  Phase 2 (haptic) confirmed scoped per BRD Layer 7. Provider stack
  decision deferred.
- **2026-05-04** — MVP 2 clarifications: chat→image-gen handoff
  confirmed (context flows on "let's design this" trigger). User
  editing scoped to import/export only. Theme catalogue locked to
  BRD §2A. Design scope inferred from prompt with override pill.
  Error model proposed (terminal panel = multi-tab Problems pane).
