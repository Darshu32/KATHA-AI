# BRD v1 vs v2 — Side-by-Side Comparison

> **Purpose:** map every requirement from the original BRD (the
> 20-page PDF) to its counterpart in [BRD_v2_KATHA_AI.md](BRD_v2_KATHA_AI.md),
> the founder-clarified version captured during the alignment session
> on 2026-05-04.
>
> **Legend:**
> - ✅ **Preserved** — same requirement, same shape
> - 🔄 **Changed** — same intent, different mechanism
> - 🆕 **New in v2** — not in v1; added in this session
> - 🟡 **Pending** — known TBD, founder will revisit
> - ❌ **Dropped** — removed from scope (none yet)

---

## Top-line shape

| Aspect | BRD v1 | BRD v2 | Change |
|---|---|---|---|
| Overall flow | Single integrated input → process → outputs | **Two context windows** (chat + image-gen) with handoff | 🆕 Major refinement |
| Vision sentence | *"Architect inputs brief → system outputs complete validated design → client feels it"* | Same end-state; added MVP 1 chat / advisory layer **before** the image-gen happens | 🔄 Expanded |
| Phases | Phase 1 = 8-week build, Phase 2 = haptic | Phase 1 = MVP 1 + MVP 2 (chat + image-gen), Phase 2 = haptic | ✅ Preserved (Phase 2 unchanged) |
| Admin/ops model | Implicit "embed" assumes static / curated knowledge | **Explicit no-admin principle**: fully self-serve, no human curation | 🆕 |
| Knowledge model | "Embed architectural standards" → static Python data | **No hardcoded knowledge**: RAG + LLM + live feeds, every datum cited | 🆕 |

---

## Layer 1 — Input & Knowledge Base

### 1A. Design Brief Input

| BRD v1 | BRD v2 | Status |
|---|---|---|
| 5 sections (Project Type, Theme, Space, Requirements, Regulatory) | Same 5 sections | ✅ |
| Single form-based input | **Two intake paths**: (a) conversational in chat (Deep mode), (b) prompt + form in image-gen | 🆕 |
| Knowledge injected at input stage (door widths, codes, climate, materials) | Same content; now sourced via RAG instead of Python literals | 🔄 |

### 1B. Architectural Knowledge Base

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Space Planning Standards (residential / commercial / hospitality with specific dims) | Same content, RAG-backed | 🔄 |
| Clearances & Egress (doors, corridors, stairs) | Same content, RAG-backed | 🔄 |
| Structural Logic (loads, column spacing, spans, foundations) | Same content, RAG-backed | 🔄 |
| MEP (HVAC, electrical, plumbing) | Same content, RAG-backed | 🔄 |
| Building Codes (NBC, IBC, accessibility, ECBC) | Same content, RAG-backed; ECBC-R 2024 added | 🔄 |

### 1C. Product Knowledge Base

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Furniture dimensions (chair, table, bed, storage) with BRD ranges | Same content, RAG-backed | 🔄 |
| Material properties (wood, metals, upholstery, finishes) | Same content, RAG-backed | 🔄 |
| Manufacturing constraints (joinery, welding, tolerances, MOQ) | Same content, RAG-backed | 🔄 |
| Cost modelling — moved to Layer 4 in v2 | Same content; pricing externalised + live feeds | 🔄 |
| Design variations (parametric, style adaptations, modular) | Preserved; LLM now generates custom theme rule packs on the fly | 🔄 |

---

## Layer 2 — Generation Engine

### 2A. Parametric Design

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Mid-Century Modern, Contemporary, Modern themes (with proportions, materials, hardware, palette) + Custom | Same 4 themes (Pedestal explicitly added per Stage 3A seed) + Custom | ✅ |
| Custom theme = "input custom dimensions + material + aesthetic" | Custom theme = LLM-generated rule pack on the fly, grounded in retrieved aesthetic chunks | 🔄 |
| Theme drives generation | **Same; plus** scope picker (architecture / interior / furniture / product) inferred from prompt | 🆕 |

### 2B. Diagram Generation

| BRD v1 | BRD v2 | Status |
|---|---|---|
| 8 diagram types (concept transparency, form, massing, volumetric, design process, solid/void, spatial organism, hierarchy) | All 8 preserved exactly | ✅ |
| Auto-generated from design parameters | Same; **also generated in chat (Deep mode mandates at least one diagram per response)** | 🆕 |

### 2C. 3D / 4D Generation — 🆕 EXPANDED

| BRD v1 | BRD v2 | Status |
|---|---|---|
| 3D mentioned only in working drawings (isometric / perspective) | **Explicit 3D pipeline**: GLTF mesh + Nano Banana Pro photoreal via reference-image | 🆕 |
| 4D not mentioned | **4D explicitly defined**: Three.js camera path → frame-by-frame → Veo / Kling polish → MP4 walkthrough | 🆕 |
| Single dimensionality per output | **3 dimensionalities × 4 scopes = 12 generation modes** | 🆕 |

---

## Layer 3 — Technical Specification

### 3A. Working Drawings

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Plan view (1:10 / 1:20) | ✅ identical |
| Elevation (1:10 / 1:20) | ✅ identical |
| Section (1:5 / 1:10) | ✅ + 1:20 added per Stage 3A code |
| 3D Isometric / Perspective (1:10) | ✅ identical |
| Detail sheets (1:1 / 1:5) | ✅ identical |
| Precision: ±1mm structural / ±2mm cosmetic / ±0.5mm material / ±5mm hardware | ✅ identical |

### 3B. Material Specification Sheet

| BRD v1 | BRD v2 | Status |
|---|---|---|
| 5 sections (Primary Structure, Secondary, Hardware, Upholstery, Finishing) | ✅ identical |
| Auto-summed totals + waste factor + adjusted cost | ✅ identical; **plus** every row carries source citation | 🔄 |

### 3C. Manufacturing Specification

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Woodworking notes (precision, joinery, finishing sequence, lead time) | ✅ identical |
| Metal fabrication notes (welding, bending, tolerance, powder coat, lead time) | ✅ identical |
| Upholstery notes (frame mounting, webbing tension, foam, zipper, stitch density, lead time) | ✅ identical |
| Assembly notes (sequence, hardware, QC checkpoints, packaging) | ✅ identical |

### 3D. MEP Specification

| BRD v1 | BRD v2 | Status |
|---|---|---|
| HVAC (room volume → ACH → CFM → ductwork → equipment → ₹ cost) | ✅ identical |
| Electrical (lux, lumens, fixtures, circuits, outlets, power capacity → ₹ cost) | ✅ identical |
| Plumbing (water demand, drain DFU, trap, slope, vent → ₹ cost) | ✅ identical |

---

## Layer 4 — Cost Modelling

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Material cost (qty × unit price + waste 10–15%) | ✅ identical |
| Labour cost (5 trades with rates) | ✅ identical |
| Overhead (workshop 30–40%, QC 5–10%, packaging 10–15%) | ✅ identical |
| Markup (designer 25–50%, manufacturer 30–60%, retail 40–100%, customisation 10–25%) | ✅ identical |
| Sensitivity ±10% on material/labour/overhead + volumes (1, 5, 10) | ✅ identical |
| Cost as a generated artefact (computed once on demand) | **Cost as live stream**: recalculates on every design change, displayed in terminal panel | 🆕 |
| Pricing source: hardcoded values | **Live feeds (MCX/FX/GST/vendors) → cached → seed → unavailable**, with freshness annotation | 🆕 |

---

## Layer 5 — Import / Export

### 5A. Export

| BRD v1 | BRD v2 | Status |
|---|---|---|
| PDF | ✅ |
| DWG / DXF | ✅ |
| Revit (.rvt) | ⚠️ via IFC4 interop (industry-standard pattern; Revit ingests IFC natively) |
| 3DS / FBX / OBJ | ✅ |
| STEP / IGES | ✅ |
| GeoJSON / IFC | ✅ |
| DOCX, XLSX, PPTX | ✅ (Stage 14 polish: assembly + maintenance sections + render gallery) |
| HTML / Interactive Web (3D viewer + cost calculator) | ✅ (Stage 14: GLTF embedded inline) |
| NC Code / G-Code | ✅ |
| CAM Prep Files | ✅ |

### 5B. Import

| BRD v1 | BRD v2 | Status |
|---|---|---|
| PDF (extract dimensions) | ✅ |
| Images (JPG/PNG) | ✅ |
| CAD (DWG/DXF/STEP) | ✅ |
| 3D Models (OBJ/FBX/GLTF) | ✅ |
| Data (CSV/Excel) | ✅ |
| Site Plans / Floor Plans | ✅ |
| Design Briefs (Text/DOCX) | ✅ |
| **Revit specifically** | 🆕 first-class; via IFC import (round-trip with export) |

---

## Layer 6 — Knowledge Integration

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Auto-application points (theme→proportions, space→standards, dimension→ergonomics, material→technical) | ✅ identical, RAG-backed |
| Spec gen (dimensions→quantities, joints→tolerances, finishes→prep + cost) | ✅ identical |
| Cost calc (material→prices, dim→qty, complexity→labour, location→regional, volume→economies) | ✅ identical |
| Quality assurance flagging (dim vs standards, load calcs, codes, manufacturing feasibility, cost reasonableness) | ✅ identical; surfaced in terminal panel "Problems" tab | 🔄 |
| Recommendations engine (proactive suggestions) | ✅ identical (2-speed: fast rule-based + LLM advisor) |
| **Citations on every datum** | 🆕 explicit transparency banner on every value (Stage 11) |

---

## Layer 7 — Haptic Interface Preparation

| BRD v1 | BRD v2 | Status |
|---|---|---|
| Dimension data as parametric variables for servo feedback | ✅ identical |
| Material haptic properties (texture IDs, temp, friction, firmness) | ✅ identical |
| Interaction parameters (adjustable dims, ranges, real-time cost triggers, material swap) | ✅ identical |
| Feedback loops ("when height changes by 1cm, cost changes by ₹X") | ✅ identical |
| JSON/XML assembly export | ✅ identical |
| Phase 1 = data structure only, Phase 2 = hardware | ✅ identical (data structure already shipped, Stage 9) |

---

## 🆕 NEW in v2 — Concepts not in v1

These are entirely new requirements that emerged from the alignment session:

### 1. Two Context Windows (MVP 1 + MVP 2)

v1 had one input → output flow. v2 splits into:
- **MVP 1 — Chat Context Window**: knowledge / discussion / planning surface
- **MVP 2 — Image Generation Context Window**: design generation surface

### 2. Three Chat Modes

v1 had no chat surface. v2 specifies:
- **Quick** mode (short, intense, ≤200 tokens default)
- **Deep** mode (continuous, mandatory diagrams, suggests present + future)
- **Auto** mode (adaptive)

### 3. Notes Sidebar (Auto-generated structured markdown)

v1 had no notes feature. v2 specifies a right sidebar in the chat
window that auto-writes notes in **structured markdown identical to
this BRD's shape** (sections, status badges, tables, bullets, code
blocks, changelog footer). Updates live as the conversation progresses.

### 4. Chat → Image-gen Handoff

v1 had no concept of multi-window flow. v2 specifies:
- Trigger phrase ("let's design this") detected in chat
- Switches to image-gen workspace
- Carries context (brief + discussion + notes + decisions) as seed

### 5. 4 Design Scopes × 3 Dimensionalities

v1 mentioned both buildings and furniture but didn't formalise. v2 specifies:
- **Scopes**: Architecture / Interior / Furniture / Product
- **Dims**: 2D / 3D / **4D (NEW)**
- 12 generation modes total
- Scope inferred from prompt; user can override

### 6. VS-Code-Style Terminal Panel

v1 had no UI specification for cost / errors. v2 specifies:
- Bottom panel of MVP 2 workspace
- Multi-tab: Cost / Problems / Generation Log / Citations
- Live cost stream (₹ low / base / high)
- Problems list with click-to-jump to element
- Streaming generation log (build-log style)
- Citations tab listing every source

### 7. Four-Class Error Model

v1 had no error model. v2 specifies:
- 🔴 **Hard error** (blocking — provider failed, malformed output)
- 🟡 **Validation warning** (rule violated)
- 🔵 **Suggestion** (recommendations engine flagged)
- 🟢 **Provenance** (citation on every datum)

### 8. Self-Serve Principle (No Admin)

v1 implied admin/ops curation. v2 explicitly forbids:
- No admin role
- No human-curated database
- All data dynamic via RAG / LLM / live feeds

### 9. Citations Everywhere

v1 didn't mention citations. v2 mandates source provenance on every
value (Stage 11 transparency banner already shipped).

### 10. Iteration Model

v1 didn't address how the user iterates. v2 specifies:
- **No direct in-canvas editing** during normal generation
- User iterates by **re-prompting**
- Editing only happens during **import / export** of files

### 11. Live Cost Stream

v1 had cost as a one-shot output. v2 has cost as a continuously-updating
stream in the terminal panel — every design change → cost recalculates.

### 12. Provider Stack Decisions

v1 didn't specify providers. v2 (deferred but documented):
- Chat: Claude Sonnet 4.6 / GPT-5.4 / Gemini 3 Pro
- Images: Nano Banana Pro
- Video: Veo 3.1 / Kling 3.0 / Seedance
- Embeddings: OpenAI / Voyage AI
- Web search: Brave / Tavily / GPT-5.4 native
- 3D meshes: Tripo3D / Meshy / Trellis

---

## 🟡 PENDING in v2 — Founder will clarify

Captured but not yet resolved:

| Item | Where in v2 |
|---|---|
| Real-time vs button-driven generation (MVP 2) | §3.5 |
| Left sidebar contents (MVP 2) | §11.2 |
| Right sidebar contents (MVP 2) | §11.2 |
| Notes persistence + edit + export (MVP 1) | §2.4 |
| Provider stack final picks | §10 |
| Error model confirmation | §11.4 |

---

## ❌ DROPPED from v1

**None.** Every requirement from BRD v1 is preserved in v2, either
identically or refined. The v2 changes are additive (more clarity)
and substitutive (RAG instead of hardcoded), never subtractive.

---

## Summary numbers

| Metric | Count |
|---|---|
| Requirements **preserved unchanged** from v1 | ~28 |
| Requirements **changed in mechanism** (same intent, different implementation) | ~12 |
| Requirements **new in v2** | 12 (the ones called out above) |
| Requirements **dropped** | 0 |
| Items **still pending** founder input | 6 |

---

## What this means for the build

**Backend:** ~90% of v1 requirements already shipped (per
[brd-compliance.md](brd-compliance.md)). The new v2 requirements
mostly need **wiring + UI**, not new engines:

- Chat surface + 3 modes + notes sidebar → frontend + thin chat router
- Image-gen workspace + terminal panel → frontend
- Chat→image-gen handoff → state + routing
- Live cost stream → SSE / WebSocket on existing cost engine
- Knowledge migration (Python literals → RAG) → using existing Stage 6 corpus
- Render pipeline → wire Nano Banana Pro into existing GLTF/Three.js path
- 4D walkthrough → new (Veo/Kling integration + Three.js camera path)

**Frontend:** essentially net-new. Next.js shell exists but unwired.
The MVP 1 + MVP 2 layouts in §11 are the build target.

**Provider integrations:** all need wiring once final picks lock.

---

## Recommended next step

Founder reviews this diff, then confirms:

1. **Anything in v2 that's wrong / missing / should be re-shaped?**
2. **The 6 pending items** (real-time mode, sidebar contents,
   notes persistence, provider picks, error model)
3. **Build sequencing** — which of these to ship first, given the
   backend-mostly-ready / frontend-net-new split

Once those land, BRD v2 becomes locked, replaces v1, and drives the
next ~6 weeks of work.

---

## Changelog

- **2026-05-04** — Created from BRD v2 + the original 20-page PDF.
  Direct comparison.
