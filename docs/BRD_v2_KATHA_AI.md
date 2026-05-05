# KATHA AI — Business Requirements Document v2

> **Source of truth:** Founder-clarified BRD derived from
> [PRODUCT_TRUTH.md](PRODUCT_TRUTH.md), captured during the alignment
> conversation on 2026-05-04. Mirrors the layer structure of BRD v1
> (the original PDF) so the two can be compared directly.
>
> **Status:** Draft for founder review. Replaces BRD v1 once approved.

---

## 0. Executive Vision

KATHA AI is a **self-serve AI agent for architecture, interior, furniture,
and product design**. It takes a designer's intent — written, sketched,
or imported — and produces the full deliverable: knowledge, diagrams,
drawings, specs, costs, and a 3D / 4D representation grounded in
authoritative sources. Phase 2 layers haptic hardware on top.

**Non-negotiable principles:**

1. **No admin role.** The product is fully self-serve. There is no
   ops team curating data behind the scenes.
2. **No hardcoded knowledge.** Every datum the user sees is dynamic —
   sourced from RAG over authoritative documents, live feeds, or
   LLM synthesis grounded in retrieved sources. Code-as-data Python
   literals are explicitly out.
3. **Cited everywhere.** Every claim, dim, price, and recommendation
   carries a provenance trail. The user can always ask *"why?"* and
   get a real answer.
4. **End-to-end deliverable.** A single workflow — brief → discussion →
   design → drawings → specs → cost → exports — with no manual hand-off
   between disconnected tools.

---

## 1. Product Architecture — Two Context Windows

KATHA delivers **one product with two distinct context windows**, each
optimised for its job. The user moves between them naturally; context
flows across.

| Context Window | Purpose | MVP |
|---|---|---|
| **Chat Context Window** | Knowledge, discussion, planning, advisory | **MVP 1** |
| **Image Generation Context Window** | Design generation (2D / 3D / 4D), specs, cost, exports | **MVP 2** |

A user can:
- Start in the **chat window** to learn / explore / plan
- Trigger a handoff (*"let's design this"*) → switches to the
  **image-gen window**, seeded with the chat's accumulated context
  (brief, decisions, notes)
- Return to chat at any time; designs stay parked in the image-gen
  window for further iteration

---

## 2. MVP 1 — Chat Context Window

### 2.1 Purpose

The chat agent is the **knowledge + discussion surface** for
architecture / interior / furniture / product design. It answers
questions, references diagrams, suggests next steps, links to
authoritative sources, and quietly takes notes the user can refer
back to.

Same shape as a general AI agent (ChatGPT / Claude / Perplexity), but
specialised to the design domain.

### 2.2 Three chat modes

| Mode | Response shape | Diagrams | Notes generated | Use case |
|---|---|---|---|---|
| **Quick** | Short, intense, dense-knowledge answer (single concept, ≤ 200 tokens by default) | Optional | No | Fast lookup ("what's the BRD door width for residential?") |
| **Deep** | Continuous multi-turn discussion. Suggests **present + future** considerations. **Diagrams MANDATORY** in every Deep response | Required | Yes — auto-generated live | Real design conversations, planning, advisory |
| **Auto** | Default / adaptive — picks Quick or Deep style based on the question's complexity | Adaptive | Yes (in Deep stretches) | When the user doesn't want to choose |

### 2.3 Response payload (mode-dependent)

Every chat response can include:

- **Knowledge body** — the actual answer, in markdown
- **Reference diagrams** — auto-generated or RAG-retrieved (TBD: §11)
- **YouTube links** — surfaced via web search or YouTube API
- **Next-step suggestions** — proactive *"you might want to consider…"*
- **Source citations** — every claim links to its RAG chunk or live source

### 2.4 Notes Sidebar (Deep mode)

A persistent **right sidebar** in the chat window that auto-generates
structured notes as the conversation progresses.

**Format:** identical to this BRD's own structure —
- Hierarchical sections (`##`, `###`)
- Status badges (✅ confirmed, 🟡 pending, ⚠️ caveat, 🔴 blocker)
- Tables for comparisons / decisions
- Bullet lists for points / next steps
- Code blocks for snippets / values when relevant
- Inline source links
- Changelog / "Updated" timestamp footer

**Behaviour:**
- Updates **live** as the conversation progresses
- New topic enters chat → new section appears in notes
- Decision reached → status flips 🟡 → ✅
- TBD item → stays 🟡 until resolved

**Open items (to confirm):**
- Persisted per chat session, per user account, or both?
- User-editable in place (click section → revise)?
- Export to `.md` / `.pdf`?

### 2.5 Knowledge sourcing — fully dynamic

No hardcoded knowledge. The chat agent grounds every answer through:

1. **RAG corpus** — authoritative documents (NBC, ECBC, IBC,
   manufacturing handbooks, climate data, vendor catalogues)
   ingested into pgvector
2. **Live data feeds** — MCX commodities, FX rates, GST rates,
   vendor SKU prices (Stage 12 plumbing, refreshed by Celery beat)
3. **LLM synthesis** — Claude / GPT / Gemini (final pick deferred,
   see §10) generates the answer, grounded in the RAG chunks +
   live data, citing each source

---

## 3. MVP 2 — Image Generation Context Window

### 3.1 Purpose

The **design surface**. Prompts (or chat-handoff context) become
drawings, models, renders, specs, and live cost. The user iterates
through prompts and import/export, not through direct canvas editing.

### 3.2 Generation scope

KATHA generates across **four design scopes** × **three
dimensionalities** = **12 generation modes**.

| Scope | 2D | 3D | 4D |
|---|---|---|---|
| **Architecture** (buildings) | Plans, elevations, sections | Massing, room volumes, BIM | Construction sequence, walkthrough |
| **Interior** (rooms) | Layout drawings | Furnished room model | Day/night cycle, walkthrough |
| **Furniture** (single piece) | Plan, elevation, section, detail | 3D mesh + materials | Material-swap morph, exploded assembly |
| **Product** (any 3D object) | Technical drawing | Parametric 3D | Operation sequence |

Scope is **inferred from the prompt** by the agent; user can override
via a pill in the UI.

### 3.3 Theme catalogue

Per BRD v1 §2A, locked for now:

- Pedestal
- Mid-Century Modern
- Contemporary
- Modern
- Custom (user-defined; LLM generates rule pack on the fly)

Will expand in future iterations.

### 3.4 Iteration model

- **No direct in-canvas editing during normal generation.**
- User iterates by **re-prompting** (modify the prompt, regenerate)
- User can edit the design only when **importing or exporting** —
  bring a Revit file in, modify it, push it out

### 3.5 Real-time vs button-driven generation

**Open** — to be decided. Two candidate models:

- **Krea-style real-time** — canvas updates live as user types
- **Explicit Generate button** — user composes prompt, hits Generate,
  waits for results

### 3.6 Chat → Image-gen handoff

When a chat conversation reaches a *"let's design this"* moment:

1. Trigger fires (explicit button or detected intent)
2. System switches to the image-gen workspace
3. Image-gen receives the **full chat context as seed**:
   - Original brief
   - Discussion history
   - Auto-generated notes (the structured markdown sidebar)
   - All decisions reached during the conversation
4. First generation runs immediately, grounded in this context

---

## 4. Layer 1 — Input & Knowledge Base

> Maps to BRD v1 Layer 1A / 1B / 1C.

### 4.1 Design Brief Input (1A)

The 5-section structured brief from BRD v1 §1A is preserved — but the
intake surface differs by MVP:

- **MVP 1 (chat):** brief is built **conversationally** through Deep
  chat. The agent extracts the 5 sections from natural-language
  discussion, captures them in the notes sidebar, asks for missing
  fields.
- **MVP 2 (image-gen):** brief either arrives via chat handoff (§3.6)
  or is composed directly in the image-gen workspace via prompt + form.

5 sections (unchanged from BRD v1):
1. Project Type — residential / commercial / hospitality / etc.
2. Theme — see §3.3
3. Space Parameters — dimensions, constraints, site conditions
4. Client Requirements — functional needs, aesthetics, budget
5. Regulatory Context — location, codes, climatic zone

### 4.2 Architectural Knowledge Base (1B)

**RAG-backed. No hardcoded.** Authoritative sources ingested into
pgvector and retrieved per query:

- Indian: NBC (parts 3, 4, 6), ECBC, ECBC-R, IS codes (875, 456, 800),
  accessibility standards
- International: IBC overlay
- Climate: zone-specific glazing, HVAC, orientation strategies
- Structural: live/dead loads, spans, foundations, seismic zones
- MEP: HVAC ACH, electrical lux, plumbing DFU per use case

### 4.3 Product Knowledge Base (1C)

**RAG-backed. No hardcoded.**

- Furniture ergonomics (chairs, tables, beds, storage with BRD ranges)
- Material properties (wood density, metal yield, leather grade,
  foam HD36, fabric durability)
- Manufacturing constraints (joinery, welding, tolerances, MOQ)
- Cost modelling (covered in Layer 4)
- Design variations / rule packs

### 4.4 Knowledge integration at input time

The knowledge bundle attached to a brief covers (auto-injected):

- Standard dimensions (doors / corridors / stairs / ceilings)
- Building code requirements (fire egress, structural, ventilation)
- Climate-specific considerations
- Regional material availability + price index

---

## 5. Layer 2 — Generation Engine

> Maps to BRD v1 Layer 2A / 2B.

### 5.1 Parametric Design (2A)

Theme + brief + knowledge context → design graph (the canonical
geometric / material / spatial representation).

The design graph is the **ground truth** that drives every downstream
artefact. Same design graph → consistent specs, costs, drawings,
and renders.

### 5.2 Diagram Generation (2B)

8 diagram types per BRD v1, all auto-generated:

1. Concept Transparency
2. Form Development
3. Massing (vertical + horizontal)
4. Volumetric
5. Design Process
6. Solid vs Void
7. Spatial Organism
8. Hierarchy

Diagrams appear in:
- **MVP 1 chat (Deep mode)** — at least one per response
- **MVP 2 image-gen** — every generation produces the full set

### 5.3 2D / 3D / 4D Generation

| Dim | Tech path |
|---|---|
| **2D** | Programmatic vector (DXF / SVG) + ControlNet polish for sketch view |
| **3D** | Design graph → GLTF mesh (asset library + parametric primitives + Tripo3D fallback for unknown objects) → Three.js / Blender headless render → Nano Banana Pro photoreal pass via reference-image workflow |
| **4D** | Three.js camera path along design graph → frame-by-frame deterministic render → per-frame photoreal polish (Veo 3.1 / Kling 3.0 — provider TBD) → MP4 walkthrough |

---

## 6. Layer 3 — Technical Specification

> Maps to BRD v1 Layer 3A / 3B / 3C / 3D. Lives entirely in **MVP 2**.

### 6.1 Working Drawings (3A)

| View | Scale | Coverage |
|---|---|---|
| Plan | 1:10 / 1:20 | Required |
| Elevation | 1:10 / 1:20 | Required |
| Section | 1:5 / 1:10 / 1:20 | Required |
| Detail | 1:1 / 1:5 | Required |
| 3D Isometric / Perspective | 1:10 | Required |

**Precision requirements:**
- Structural dimensions: ±1 mm
- Cosmetic dimensions: ±2 mm
- Material thickness: ±0.5 mm
- Hardware placement: ±5 mm

### 6.2 Material Specification Sheet (3B)

5 sections (per BRD v1):
1. Primary Structure
2. Secondary Materials
3. Hardware
4. Upholstery (if applicable)
5. Finishing

Each row: name, grade, finish, supplier, lead time, cost band, source citation.

### 6.3 Manufacturing Specification (3C)

Per trade — woodworking, metal fabrication, upholstery, assembly —
with QA gates, packaging notes, lead times.

### 6.4 MEP Specification (3D)

When architectural — HVAC (volume → ACH → CFM → ductwork → equipment),
Electrical (lux → fixtures → circuits), Plumbing (demand → drain
sizing → trap → vent). Each block carries an auto-calculated cost.

---

## 7. Layer 4 — Cost Modelling & Live Estimation

> Maps to BRD v1 Layer 4A. **Lives in the MVP 2 terminal panel.**

### 7.1 Cost engine

Per BRD v1 §4A formula:

```
Final Price = (Material + Labour + Overhead) × (1 + Margin %)
```

With:
- Material — qty × unit price + waste factor (10–15%)
- Labour — trade hours × rate per BRD §1C trades (5 trades)
- Overhead — workshop (30–40%) + QC (5–10%) + packaging (10–15%)
- Margin — designer (25–50%), manufacturer (30–60%), retail (40–100%),
  customisation premium (10–25%)

### 7.2 Live data integration

Every price is sourced through the **fallback chain**:

```
Live feed (MCX/FX/GST/vendor) → cached → seed → unavailable
```

with **freshness annotation** on every value (LIVE / RECENT / STALE / EXPIRED).

### 7.3 Sensitivity analysis

Per BRD v1 §4D:
- ±10% shock on material / labour / overhead → impact on final
- Volume scenarios: 1 / 5 / 10 pieces

### 7.4 Live cost in the UI

The cost engine **runs continuously** against the current design state.
Every change → recalculation → updated numbers in the **terminal
panel** (see §11.2).

```
₹ 1,42,500 (low)   ₹ 1,68,000 (base)   ₹ 1,95,000 (high)
↓ updates on every design change
```

---

## 8. Layer 5 — Import / Export

> Maps to BRD v1 Layer 5A / 5B.

### 8.1 Import (5B) — user → KATHA

Importing existing artefacts grounds generation in real-world geometry:

| Format | Use case | Priority |
|---|---|---|
| **Revit (.rvt)** | Architectural BIM hand-off | **First-class** |
| DWG / DXF | 2D CAD drawings | Required |
| STEP / IGES | Parametric solid CAD | Required |
| OBJ / FBX / GLTF | 3D mesh / visualisation | Required |
| PDF | Reference designs, specs | Required |
| Images (JPG/PNG) | Style / material reference | Required |
| Site plans | Existing spaces / context | Required |
| CSV / Excel | Specifications, pricing data | Required |
| Design briefs (Text / DOCX) | Client requirements parsing | Required |

**Note on Revit:** native `.rvt` is closed — interop via IFC4 import.
Architect exports IFC from Revit → KATHA reads geometry, dims,
materials. Round-trip back to Revit via IFC export.

### 8.2 Export (5A) — KATHA → user

15 formats per BRD v1 §5A, all auto-generated per design:

**Documents:**
- PDF, DOCX, XLSX, PPTX, HTML / interactive web

**CAD / 3D:**
- DWG / DXF, OBJ, GLTF, FBX

**BIM / specialist:**
- IFC4 (Revit interop), STEP, IGES

**Manufacturing:**
- G-code, CAM prep (nesting + assembly guides)

**Data:**
- GeoJSON

All exports include source citations + provenance trail (Stage 11
transparency).

---

## 9. Layer 6 — Knowledge Integration & Transparency

> Maps to BRD v1 Layer 6.

### 9.1 Where knowledge auto-applies

| Stage | Auto-applied knowledge |
|---|---|
| Brief intake | Standard dimensions, codes, climate, regional materials |
| Generation | Theme proportions, ergonomic ranges, structural feasibility |
| Specs | Quantities from dims, tolerances from joints, prep from finishes |
| Cost | Live prices, regional adjustments, volume economies |
| QA | Dimension flags, code compliance, structural check, manufacturing feasibility |

### 9.2 Recommendations engine

Two-speed (existing Stage 10 work):
- **Fast (rule-based)** — always-on; flags during generation
- **LLM (deep)** — on-demand; generates proactive advisory

### 9.3 Transparency banner (citations everywhere)

Every datum carries:
- Source identifier (RAG chunk ID, MCX timestamp, NBC clause, etc.)
- Confidence score (0–1, plus human-readable factors)
- Freshness (for time-sensitive sources)

Surfaces in the UI as click-through citations on every value.

---

## 10. Provider Stack

> **🟡 DEFERRED** — final picks pending founder confirmation. Options
> on the table:

| Layer | Options | Notes |
|---|---|---|
| **Chat / agent reasoning** | Claude Sonnet 4.6 (codebase wired, benchmark winner for architectural reasoning) / GPT-5.4 (founder initial pick) / Gemini 3 Pro (pairs with Nano Banana) | See PRODUCT_TRUTH.md §4 for cost analysis |
| **Image generation** | Nano Banana Pro (founder pick — Veras-validated for architecture) | Likely confirmed |
| **Video / 4D** | Veo 3.1 (Google ecosystem) / Kling 3.0 (best narrative) / Seedance 2.0 (cheapest, Fenestra picks) | Pending |
| **Embeddings** | OpenAI text-embedding-3-small (current) / Voyage AI 3 (better retrieval) | Likely upgrade to Voyage |
| **Web search** (for YouTube links + grounding) | Brave / Tavily / GPT-5.4 native | Pending |
| **3D mesh generation** (per-furniture) | Tripo3D / Meshy / Trellis | For replacing primitive boxes |
| **Vector DB** | pgvector (current) | Confirmed |

---

## 11. UI / UX Specification

### 11.1 MVP 1 — Chat Context Window

```
┌─────────────────────────────────────┬──────────────────────┐
│                                     │                      │
│   CHAT TRANSCRIPT                   │   NOTES SIDEBAR      │
│   (messages, diagrams, links)       │   (auto-generated    │
│                                     │    structured        │
│   Mode pills: [Quick] [Deep] [Auto] │    markdown,         │
│                                     │    same shape as     │
│   Input box                         │    this BRD)         │
│                                     │                      │
└─────────────────────────────────────┴──────────────────────┘
```

### 11.2 MVP 2 — Image Generation Context Window

```
┌──────────┬────────────────────────────────────┬──────────┐
│          │                                    │          │
│   LEFT   │   IMAGE CANVAS                     │  RIGHT   │
│ SIDEBAR  │   (renders, drawings, 3D / 4D      │ SIDEBAR  │
│          │    viewer; switch view via tabs)   │          │
│   🟡     │                                    │   🟡     │
│ contents │   Theme picker / scope override    │ contents │
│ pending  │   pills here or in left sidebar    │ pending  │
│          │                                    │          │
├──────────┴────────────────────────────────────┴──────────┤
│ Cost  │ Problems (3) │ Generation Log │ Citations         │
├───────────────────────────────────────────────────────────┤
│ ₹ 1,42,500 (low)  ₹ 1,68,000 (base)  ₹ 1,95,000 (high)    │
│ ↓ updates on every design change                          │
└───────────────────────────────────────────────────────────┘
```

### 11.3 Terminal panel — VS-Code-style multi-tab

| Tab | Content |
|---|---|
| **Cost** | Live ₹ low / base / high; updates on every change |
| **Problems** | Counts + scrollable list of all 🔴 🟡 🔵 issues; click to jump to element |
| **Generation Log** | Streaming text of what the agent is doing right now (build-log style) |
| **Citations** | Every source the design draws on (RAG chunks, NBC clauses, MCX timestamps) |

### 11.4 Error / problems model

| Class | Severity | Trigger | Example |
|---|---|---|---|
| 🔴 **Hard error** | Blocking | System / API failed | "Image gen failed — Nano Banana 500. Retry?" |
| 🟡 **Validation warning** | Non-blocking | Generation violates a rule | "Door width 720 mm < NBC min 800 mm" |
| 🔵 **Suggestion** | Info | Recommendations engine flagged | "Consider walnut over oak for this theme" |
| 🟢 **Provenance** | Info | Source citation on every datum | "Price = MCX live, 2 hrs ago" |

---

## 12. Non-Functional Requirements

| NFR | Target |
|---|---|
| Brief input completion | ≤ 2 minutes (per BRD v1) |
| Full design generation | ≤ 30 seconds (per BRD v1) — covers brief → 8 diagrams + 5 drawings + 3 specs + cost + 15 exports + haptic data |
| Chat response latency (Quick) | ≤ 2 seconds |
| Chat response latency (Deep) | ≤ 8 seconds (longer for diagram generation) |
| Cost engine recalculation on change | ≤ 500 ms |
| Citation click-through resolution | ≤ 200 ms |
| Concurrent users (target launch) | 1k DAU |
| Uptime SLA | 99.5% |
| Data residency | India primary (Mumbai region) for Indian customers |

---

## 13. Data Sources & RAG Corpus

### 13.1 Authoritative document corpus (ingested into pgvector)

- NBC (parts 3, 4, 6) and amendments
- ECBC + ECBC-R
- IBC + relevant chapters
- IS codes (875, 456, 800)
- Accessibility / fire codes
- Manufacturing handbooks (woodworking, metal, upholstery)
- Climate zone atlas (Indian + global)
- Vendor catalogues (Jaquar, Kohler, Asian Paints — already started)
- Material property databases (timber, metals, fabrics)

### 13.2 Live data sources (Stage 12)

- MCX commodity prices (steel, aluminium, copper)
- FX rates (USD/INR, EUR/INR)
- GST classification (CBIC HSN codes)
- Vendor SKU prices (Jaquar, Kohler, Asian Paints) — refreshed daily

### 13.3 LLM-generated knowledge

For low-stakes, high-variation answers (e.g., theme rule packs for
custom themes, recommendation prose) the LLM generates fresh,
grounded in retrieved chunks.

---

## 14. Roadmap & Acceptance Criteria

### 14.1 Phase 1 — MVP 1 + MVP 2 (current focus)

| Stage | Deliverable | Status |
|---|---|---|
| MVP 1 wiring | Chat window with 3 modes + notes sidebar wired to existing backend | 🟡 Pending |
| Knowledge migration | RAG-backed Layer 1B/1C (replace hardcoded Python) | 🟡 Pending |
| MVP 2 wiring | Image-gen workspace + 4-zone UI + terminal panel | 🟡 Pending |
| Render pipeline | GLTF → Nano Banana Pro for hero + multi-view | 🟡 Pending |
| Chat→image-gen handoff | Context flow on "let's design this" | 🟡 Pending |
| Live cost in terminal | Cost engine streams to terminal panel on every change | 🟡 Pending |
| 4D generation | Camera-path walkthrough → Veo / Kling | 🟡 Pending |
| Provider stack lock | Final picks for chat / image / video / embeddings | 🟡 Pending |

### 14.2 Phase 1 Acceptance — done when:

- [ ] User completes a brief in chat (≤ 2 min) → triggers handoff →
      sees full deliverable (renders + 8 diagrams + 5 drawings + 3 specs + cost + 15 exports) in image-gen workspace within 30 s
- [ ] Every value in the deliverable cites a source (RAG / live / LLM)
- [ ] Notes sidebar accurately reflects the chat conversation
- [ ] Terminal panel shows live cost, live problems, live generation log, live citations
- [ ] Importing a Revit (IFC) file populates the design graph
      correctly and exports back round-trip
- [ ] No Python-literal knowledge in the runtime path
- [ ] Frontend wired to backend; user can use the product without
      touching `curl`

### 14.3 Phase 2 — Haptic Interface

Per BRD v1 (Aug–Sep 2026):

- Order haptic arm hardware (UR3 or custom)
- Build haptic driver / middleware (consumes the Stage 9 data structure)
- Material haptic library mapping
- Client haptic session workflow
- First paid haptic session

The haptic-ready data structure is **already shipped** (Stage 9,
[app/haptic/](../backend/app/haptic/)).

---

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Photoreal renders don't match design graph dims | Use reference-image workflow (Veras pattern) — Three.js depth render → Nano Banana restyle. Geometry preserved by source image |
| 30-second SLA violated by LLM latency | Parallelise tool calls; aggressive prompt caching (Claude); batch async work (drawings / specs in parallel with renders) |
| RAG hallucination on regulatory codes | Force structured extraction with schema validation; numerical bounds checks; low-confidence flag in transparency banner |
| Provider lock-in (single API outage) | Abstraction layer at `app/agents/runtime/` already supports multi-provider; build fallback path for each layer |
| Vendor scrapers brittle | Stub-mode pattern (Stage 12, ADR 0006) — broken parser degrades to stale data + ops alert, not API outage |
| Hardcoded knowledge drift | Knowledge migration is a hard requirement before public launch (covered in §14.1) |
| Frontend not yet wired to backend | Tracked as a roadmap blocker in §14.1; UI layout pending in §11 |

---

## 16. Appendix — What's already built (backend)

This BRD describes the target. The current backend ships ~90% of the
machinery, just not yet end-to-end wired to a frontend or to the
chat/image-gen split this BRD specifies.

| Capability | Where it lives |
|---|---|
| 81 agent tools | `backend/app/agents/tools/` |
| RAG corpus + embeddings | `backend/app/corpus/`, `backend/app/memory/` |
| Live data feeds | `backend/app/feeds/` (Stage 12) |
| Cost engine + sensitivity | `backend/app/services/cost_engine_service.py`, `sensitivity_service.py` |
| 8 diagram services | `backend/app/services/diagrams/` |
| 5 drawing services | `backend/app/services/drawings/` |
| 3 spec sheet services | `backend/app/services/specs/` |
| 15 exporters | `backend/app/services/exporters/` |
| 9 importers | `backend/app/services/importers/` |
| Haptic data structure | `backend/app/haptic/` (Stage 9) |
| Reasoning transparency | `backend/app/provenance/`, `backend/app/agents/confidence.py` |
| Rate limit / OTEL / error envelope | `backend/app/middleware/`, `backend/app/observability/` |

What's **NOT yet built**:
- Chat → image-gen handoff
- Notes sidebar (live structured-markdown generator)
- Live cost streaming to terminal panel
- 2D / 3D / 4D render pipeline (stub at `app/workers/tasks.py:79`)
- Frontend wiring (Next.js shell exists, not connected)
- Knowledge migration from Python literals → RAG
- Provider stack final lock

---

## Changelog

- **2026-05-04** — v2 created from PRODUCT_TRUTH.md alignment session.
  Mirrors BRD v1 layer structure for direct comparison.
