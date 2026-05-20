# Phase 2 Procedure

> **Status:** Living forward-plan doc. Phase 1 is shipped
> (see [`brd-compliance.md`](brd-compliance.md)). This document
> captures the next-step procedure: hardening, deferred Phase 2
> candidates, and the haptic hardware path the BRD anticipates.
>
> **Last reviewed:** 2026-05-18 (after Stage 15 — Tier 2/3 DB
> migration + Massing diagram).

---

## 1. Status check — where we actually are

Phase 1 BRD (§1A through §6, plus Layers 6 + 7) is **100% feature-complete** per `brd-compliance.md`. Confirmed by directory verification on 2026-05-18:

| Surface | Count | Location |
|---|---|---|
| Agent tools | 78 (Stage 10) → ~27 modules visible at audit | `backend/app/agents/tools/` |
| Exporters | 16 (PDF · DOCX · XLSX · PPTX · HTML · DXF · OBJ · GLTF · FBX · IFC · STEP · IGES · gcode · cam_prep · GeoJSON · _synthesis) | `backend/app/services/exporters/` |
| Importers | 9 (PDF · DOCX · XLSX · CSV · DXF · OBJ · STEP · image · text) | `backend/app/services/importers/` |
| Diagram services | 9 (incl. new Massing) | `backend/app/services/*_diagram_service.py` |
| Working drawings | 5 (plan · elevation · section · isometric · detail) | `backend/app/services/*_view_drawing_service.py` |
| Spec sheets | 4 (material · manufacturing · MEP · cost) | `backend/app/services/*_spec_service.py` |
| Haptic data layer | catalog + exporter + validator + 6 tables | `backend/app/haptic/`, alembic 0020 |

Post-BRD work shipped (Stages 12–15):
- **Stage 12** — Live data feeds (MCX + FX + GST + vendor scrapers) with anomaly alerts
- **Stage 13** — Project types expansion, editorial UI
- **Stage 14** — Export polish (DOCX maintenance sections, PPTX render gallery, HTML self-contained viewer)
- **Stage 15** — Tier 2/3 knowledge externalisation to versioned DB rows + Massing diagram (closes "no hardcoded knowledge")

> ⚠️ `docs/PHASE1_GAP_ANALYSIS.md` is **stale** (predates Stage 10). Treat `brd-compliance.md` as authoritative.

---

## 2. Pre-Phase-2 bridge (now → ~July 2026)

Things to do before haptic hardware arrives. Order is sequencing, not priority.

### 2A. Production hardening (BRD Week 9 — overdue)
- Performance optimisation pass (cold-start, render times, export throughput)
- Beta with 2–3 real architectural projects end-to-end
- Comprehensive user-facing documentation (`docs/foundations.md` is internal-facing)
- Observability — confirm OpenTelemetry coverage on agent tool calls + exports

### 2B. Open product items (from `PRODUCT_TRUTH.md`)
- **Deep / Quick / Auto mode toggle UI** — backend is mode-aware; UI selector incomplete
- **User-editable inline notes** — sidebar is LLM-authored; editing not wired
- **Two-window UX clarification** — side-by-side vs. switchable vs. dual app (locked decision missing)
- **Mobile chat-only build** — desktop ships `/chat` + `/design`; mobile is `/chat` only per project scope

### 2C. EU launch infra (per user memory)
- EU hosting v1 (satisfies GDPR + DPDPA simultaneously)
- EU Representative appointment (legal requirement, not code)
- Region-routed provider abstraction confirmed for Azure / Vertex / Anthropic
- GDPR-style profile delete via agent tool (deferred Phase 2 candidate — needs self-serve surface before broader rollout)

### 2D. Deferred Phase 2 candidates (per `brd-compliance.md`)
Trigger-based, not calendar-based:

| Candidate | Trigger to activate |
|---|---|
| Native `.rvt` export via Windows worker / pyRevit / ODA SDK | Customer signs requiring native Revit project files (IFC currently covers ~80%) |
| Machine-specific G-code post-processors (Fanuc, Haas, Mach3) | Manufacturing partner signed |
| Strict-mode haptic export (fail on unmapped material) | Hardware vendor requests strict semantics |
| Semantic recall over chat turns (Stage 5E / 8B) | UX pain on long sessions |
| GDPR profile-delete agent tool | Before EU rollout closes |

### 2E. Provider stack — known stubs
- **Vertex Gemini** image generation — provider abstraction in place, integration deferred
- **Meshy v1 → self-host** 3D mesh — not yet integrated
- **Veo 3** 4D / video — deferred to post-MVP per memory

---

## 3. Phase 2 — Haptic Hardware Integration (BRD Aug–Sept 2026)

The BRD frames Phase 2 as **hardware integration on top of the data structure already shipped in Stage 9**. The data contract is `docs/haptic/data-structure.md`; the JSON payload is end-to-end production.

### Procedure (BRD §Phase 2 Preview, expanded)

1. **Hardware selection + procurement** — UR3 (Universal Robots) or custom haptic arm. 6–8 week lead time. *Decision input: budget, workspace footprint, payload spec.*
2. **Driver / middleware build** — translate `build_haptic_payload()` output into servo commands. Treats `signature_data` patterns (`linear_grain`, `fine_pebble`, `weave`, `smooth`, `linear_brush`, `rough`) as motion profiles. Reads `temperature_celsius` for thermal element, `coefficient` for friction surface, `firmness_scale` × `density` for pushback + perceived weight.
3. **Material haptic library validation** — physical samples vs. catalog values; tune `amplitude_um`, `grain_freq_per_cm` against hardware fidelity.
4. **Session workflow** — client books haptic session → architect opens design in KATHA → `export_haptic_payload` → arm consumes → real-time feedback loops fire on adjustment (the rules in `haptic_feedback_loops`).
5. **First paid session** — proof-of-concept revenue milestone per BRD.

**Key insight from BRD:** *"Haptic plugs in. Software doesn't get rewritten."* All architectural work for this is done — Phase 2 is squarely a hardware + driver engineering task.

---

## 3.5. Active sprint — Frontend (next 5 days from 2026-05-19)

Founder direction 2026-05-19: focus purely on frontend for 5 days, then engine-tool wiring, then API keys + prototype handoff to beta architect.

| Day | Deliverable | Status |
|---|---|---|
| 1 | `/design` layout restructure — left accordion (Brief / Space / Requirements / Regulatory), right sidebar tabbed shell | pending |
| 2 | **Views tab** — 5 working drawings + 8 diagrams click-to-swap canvas | pending |
| 3 | **Cost panel** moves out of terminal into right sidebar + **Export button** opens 15-format modal | pending |
| 4 | **Recommendations panel** (two-speed engine) + extended Validation/Citations + Version chip wiring | pending |
| 5 | Polish + **Haptic-ready badge** + responsive + accessibility | pending |

Open product questions to lock before Day 1:
- Tabs vs accordion in right sidebar (recommended: tabs)
- Brief in sidebar accordion vs separate route (recommended: sidebar)
- Top bar redundant strip (recommended: kill)
- Dark sidebars on `/design` revisit (reference: Autodesk Forma — see `docs/research/architecture-ai-platforms.md`)

After Frontend sprint:
1. **Engine-tool wiring** — verify every UI surface fires the right backend agent tool; end-to-end test
2. **API keys + prototype** — wire Anthropic / OpenAI / Vertex / MCX feed keys; run a real architectural project end-to-end; hand to a beta architect

## 4. Sequencing recommendation

```
NOW ──────────────────────────────────────────────► AUG 2026
│
├── Week 1–2: Production hardening (2A) + beta projects
│
├── Week 3–4: Open product items (2B) — UI mode toggle, editable notes
│              EU infra spike (2C) — hosting + GDPR delete tool
│
├── Week 5–6: Provider stubs (2E) — Vertex Gemini wired if needed for
│              image-gen window; Meshy decision (self-host vs SaaS)
│
├── Week 7+:  Hardware procurement begins (Phase 2)
│             Deferred candidates (2D) activate on real triggers only
│
└── Aug–Sept: Haptic hardware arrives + driver build + first session
```

**Avoid:** building Phase 2D candidates speculatively. Each has an explicit business trigger; pulling them forward burns time before the haptic milestone.

---

## 5. Open questions before locking the next stage

| # | Question | Status (2026-05-18) |
|---|---|---|
| 1 | **Beta architects** — 2–3 test users for product validation (not paying pilots) | 🟡 Open. Confirmed 2026-05-18 as **testing-only** scope — recruit testers who will run real projects through KATHA to surface bugs / UX issues / export-compatibility issues. Not commercial relationships. |
| 2 | **Haptic hardware vendor + budget** — UR3 (~$23K) vs custom | 🟡 To be decided. Lock by July to hit BRD Aug timing. *Phase 1 haptic data structure already shipped per BRD §Layer 7 — this decision is purely for Phase 2 hardware procurement.* |
| 3 | **Mode toggle UX** (Quick/Deep/Auto) + two-window layout (side-by-side vs switchable vs dual route) | Deferred to upcoming frontend implementation phase (confirmed 2026-05-18) |
| 4 | **EU Representative** — named legal firm before EU traffic | 🟡 **Parked for now** (confirmed 2026-05-18). Not a current blocker; revisit before EU launch. |
| 5 | **Image-gen window scope** — is `/design` workspace the image-gen window? | ✅ **Confirmed 2026-05-18.** `/design` IS the image-gen window per `PRODUCT_TRUTH.md` two-context-window model. No third surface to build. |

---

## 6. What this doc is not

- Not a status dashboard — Stage notes + git log are authoritative
- Not a feature spec — see `PRODUCT_TRUTH.md` for product shape, `BRD_v2_KATHA_AI.md` for the source spec
- Not a Phase 1 closure doc — see `brd-compliance.md`

Update this doc when a section in §2 lands or §3 procedure activates.
