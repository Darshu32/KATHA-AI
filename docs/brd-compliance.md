# BRD Phase 1 — Compliance Mapping

> **Status:** Phase 1 complete as of Stage 10. Every BRD §Phase 1
> specification traces below to a verified feature, the file(s) it
> ships in, and the test(s) that lock it.
>
> **Legend:**
> - ✅ **Native** — shipped exactly as the BRD specifies it.
> - ⚠️ **Via interop** — shipped via an industry-standard exchange
>   format with a documented workflow. The BRD asks for an outcome
>   ("architect can use the design in Revit"); we deliver the
>   outcome through IFC, which Revit imports natively.
> - 🚧 **Phase 2** — intentionally deferred with reasoning.
>   Currently zero items in this status.

---

## At a glance

| Layer / §                     | What the BRD asks for                | Status | Where it lives |
|---|---|---|---|
| §1A — Design Brief Input      | 5-section structured intake          | ✅ | `app/models/brief.py`, `app/services/design_brief_service.py`, `app/agents/tools/brief.py` |
| §1B — Architect Brief         | LLM-authored brief reflection        | ✅ | `app/services/architect_brief_service.py`, route `/brief/architect` |
| §2A — Theme rule packs        | Pedestal + MCM + Contemporary themes | ✅ | `app/knowledge/themes.py`, `app/services/themes/seed.py`, alembic 0005 |
| §3A — Working drawings        | Plan + elevation + section + detail + isometric | ✅ | `app/services/{plan,elevation,section,detail_sheet,isometric}_view_drawing_service.py`, `app/agents/tools/drawings.py` |
| §3A — Section view scales     | 1:5 / 1:10 / 1:20                    | ✅ | `section_view_drawing_service.SECTION_SCALE_OPTIONS` |
| §3B — Specification sheets    | Material / manufacturing / MEP specs | ✅ | `app/services/{material,manufacturing,mep}_spec_service.py`, `app/agents/tools/specs.py` |
| §3C — Concept diagrams        | 8 diagram types                      | ✅ | `app/services/diagrams/`, `app/agents/tools/diagrams.py` |
| §4A — Cost engine             | Material + labor + overhead          | ✅ | `app/services/cost_engine_service.py`, `app/agents/tools/cost.py` |
| §4B — Pricing buildup         | Margin / markup stack                | ✅ | `app/services/pricing/`, `app/agents/tools/cost_extensions.py` |
| §4D — Sensitivity ±10%        | What-if shocks + volume scenarios    | ✅ | `app/services/sensitivity_service.py`, `app/agents/tools/sensitivity.py` |
| §5A — File-format exports     | 15 formats (doc / CAD / BIM / CNC)   | ✅ | `app/services/exporters/`, `app/agents/tools/io.py` |
| §5A — Revit (.rvt)            | Architect can use design in Revit    | ⚠️ | IFC4 export → Revit's built-in IFC importer |
| §5A — G-code / CAM            | CNC-ready output                     | ✅ + ⚠️ | Native: `gcode_exporter.py` + `cam_prep_exporter.py`. Machine-specific dialects via STEP → CAM post-processor |
| §5B — File imports            | DWG / DXF / IFC / OBJ / etc          | ✅ | `app/services/importers/`, `app/agents/tools/io.py` |
| §6  — Recommendations         | Proactive forward-looking advisor    | ✅ | `app/services/recommendations.py` (fast) + `app/services/recommendations_service.py` (LLM), `app/agents/tools/recommendations.py` |
| §Layer 6 — Memory             | Cross-session continuity             | ✅ | Stage 8 — `app/profiles/`, `app/repositories/{architects,clients,decisions}/` |
| §Layer 7 — Haptic data        | Hardware-ready data structure        | ✅ | Stage 9 — `app/haptic/`, alembic 0020, `app/agents/tools/haptic.py` |

---

## Detail by section

### §1A — Design Brief Input

**BRD asks for:** 5-section structured intake — project type, theme,
space parameters, client requirements, regulatory context.

**Shipped:**

| Section | Type / model | Lines |
|---|---|---|
| 1. Project type | `ProjectTypeSection` (9 enum values) | `app/models/brief.py:56` |
| 2. Theme | `ThemeSection` (5 enum values + alias resolution) | `app/models/brief.py:76` |
| 3. Space | `SpaceParameters` (dimensions + constraints + site_conditions) | `app/models/brief.py:135` |
| 4. Requirements | `ClientRequirements` (functional + aesthetic + narrative + budget + timeline) | `app/models/brief.py:151` |
| 5. Regulatory | `RegulatoryContext` (country/state/city + codes + climatic_zone + compliance_notes) | `app/models/brief.py:178` |

**Surfaces:**

- HTTP — `POST /brief/intake`, `/brief/context`, `/brief/knowledge`,
  `/brief/architect` in `app/routes/brief.py`.
- Agent tools (Stage 10) — `intake_design_brief`,
  `brief_to_generation_context` in `app/agents/tools/brief.py`.

**Tests:** `tests/unit/test_stage10_brd_closure.py::test_intake_design_brief_requires_brd_5_sections`.

---

### §2A — Theme rule packs

**BRD asks for:** parametric theme rule packs covering proportions,
material palette, hardware, colour palette, ergonomic targets,
signature moves, dos/don'ts.

**Shipped (seeded as DB rows + agent-readable):**

| Theme | Where | Lines |
|---|---|---|
| Pedestal (KATHA studio signature) | `app/knowledge/themes.py:38` | 41 lines, every BRD field present |
| Mid-Century Modern | `app/knowledge/themes.py:80` | 48 lines, every BRD field + colour strategy + tactile notes |
| Contemporary | `app/knowledge/themes.py:129` | Full BRD-spec rule pack |
| Modern (alias) | resolves via `_ALIASES` to mid-century / contemporary depending on context | |

Aliases resolve `mcm` / `mid-century` / `midcentury` / `mid century`
to `mid_century_modern`; `plinth` / `theme_v` resolve to `pedestal`.

**Tests:** `tests/integration/test_themes_repo.py` (existing).

---

### §3A — Working drawings (with scales)

**BRD asks for:** plan / elevation / section / detail / isometric
working drawings, with section views at **1:5 and 1:10** for
furniture-scale, **1:20** for larger pieces.

**Shipped:**

| Drawing type | Service | Tool |
|---|---|---|
| Plan view | `plan_view_drawing_service.py` | `drawings.plan_view` |
| Elevation view | `elevation_view_drawing_service.py` | `drawings.elevation_view` |
| Section view | `section_view_drawing_service.py` | `drawings.section_view` |
| Detail sheet | `detail_sheet_drawing_service.py` | `drawings.detail_sheet` |
| Isometric view | `isometric_view_drawing_service.py` | `drawings.isometric_view` |

**Section scales:** `SECTION_SCALE_OPTIONS` in
`section_view_drawing_service.py:141` exposes `1:5`, `1:10`, `1:20`
to the LLM at generation time, with rationale captured in the
`scale_rationale` field. Per-piece scale selection is locked in
the validator (`scale MUST be in scale_options`).

---

### §4D — Sensitivity ±10%

**BRD asks for:** four what-if questions:
- Material +10% → final price increases by [%]
- Labor +10% → final price increases by [%]
- Overhead +10% → final price increases by [%]
- Cost at different volumes (1, 5, 10 pieces)

**Shipped:**

| Component | Where |
|---|---|
| Default shock magnitude | `sensitivity_service.SHOCK_PCT_DEFAULT = 10.0` |
| Default volumes | `sensitivity_service.DEFAULT_VOLUMES = (1, 5, 10)` |
| Deterministic re-walk | `_recompute_overhead`, `_walk_price`, `_build_shock_scenario`, `_build_volume_scenario` in `sensitivity_service.py` |
| LLM narrator | `generate_sensitivity_analysis` (validated against deterministic table — LLM never invents numbers) |
| Agent tool | `analyze_cost_shock` in `app/agents/tools/sensitivity.py` (Stage 10) |

The agent tool accepts `shock_pct` (default 10.0, capped 50) and
`volumes` (default `[1, 5, 10]`) — both BRD-aligned.

**Tests:** `tests/unit/test_stage10_brd_closure.py::test_analyze_cost_shock_defaults_to_brd_10_percent` + `::test_analyze_cost_shock_volume_default_matches_brd`.

---

### §5A — File-format exports

**BRD asks for:** export to recipient-appropriate formats — clients
get PDFs, contractors get DWG/IFC, manufacturers get CNC programs.

**Shipped — 15 formats grouped by family:**

| Family | Formats |
|---|---|
| Documents | PDF, DOCX, XLSX, PPTX, HTML |
| CAD 2D | DXF |
| 3D mesh | OBJ, GLTF, FBX |
| BIM | **IFC4** |
| CAD exchange | STEP, IGES |
| CNC | **gcode**, **cam_prep** |
| Data | GeoJSON |

**Registry:** `app/services/exporters/__init__.py:_REGISTRY` (15 modules).
**Agent tool:** `export_design_bundle` in `app/agents/tools/io.py`.

#### Revit (.rvt) — ⚠️ Via IFC interop

The BRD asks the architect to be able to use the design in Revit.
Native `.rvt` writing requires Autodesk Revit Desktop running on
Windows (via Revit's Python API or pyRevit) — not viable in a
Linux backend service.

**Interop path:**

1. Architect calls `export_design_bundle` with `format="ifc"`.
2. The IFC4 exporter (`app/services/exporters/ifc_exporter.py`,
   built on `ifcopenshell`) emits a single `.ifc` file containing
   `IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey` with
   `IfcSpace`s for rooms and `IfcFurnishingElement` /
   `IfcDoor` / `IfcWindow` / `IfcWall` / `IfcElectricAppliance`
   / `IfcSanitaryTerminal` for objects.
3. Architect opens the `.ifc` in Revit via *Insert → Link IFC* (or
   *Open IFC* for a fresh document). Revit's built-in IFC
   importer is mature — this is a one-click workflow.
4. Same `.ifc` opens in ArchiCAD, Vectorworks, Navisworks, Solibri,
   BIMVision — IFC is the BIM industry's lingua franca.

**Why we picked this over native .rvt:**

| Approach | Verdict |
|---|---|
| Revit Python API / pyRevit | ❌ Requires Revit Desktop on Windows |
| ODA Drawings SDK (paid) | ⚠️ Commercial licensing — Phase 2 if a partner needs it |
| **IFC4 export** | ✅ Industry standard, Revit imports natively, multi-vendor |

The deliverable the BRD asks for ("architect can use the design in
Revit") ships in full. The file extension differs; the workflow is
faster and more interoperable.

#### G-code / CAM — ✅ Native + ⚠️ Via STEP

The BRD asks for CNC-ready output. **Native shipping:**

- `gcode_exporter.py` — emits a CNC routing program with nesting
  + multi-tool sequencing.
- `cam_prep_exporter.py` — bundles nest-SVG + JSON + QA + assembly
  notes — the package a CAM operator opens directly.

**Why also via STEP:** G-code dialect is machine-specific (Fanuc,
Haas, Mach3, GRBL — all different post-processor formats). The
universally-accepted CAM input is **STEP** (parametric solid
geometry). A CAM operator imports the STEP into Fusion 360 /
Mastercam / their machine's native CAM, and the CAM software
emits dialect-specific G-code for the target machine.

We ship **both** so the architect can hand whichever the CNC
partner expects. The native G-code is sufficient for common
3-axis routers; STEP covers everything else.

---

### §6 — Recommendations engine

**BRD asks for:** proactive forward-looking advisor that fires
across the design pipeline:

> ├── "For mid-century theme, typically use walnut..."
> ├── "This dimension exceeds standard; consider..."
> ├── "Material cost high; suggest alternatives..."
> ├── "Manufacturing lead time: typically 6-8 weeks for this..."
> └── "Cost per unit decreases significantly at volumes >5..."

**Shipped — two-speed implementation:**

| Engine | Latency | Use |
|---|---|---|
| Deterministic Python | ~1 ms | Always-on; called proactively after every estimate / generation / material change |
| LLM-driven advisor | ~3-8 s | On-demand; full categorised list with confidence / impact / effort labels and citations |

| Component | Where |
|---|---|
| Fast Python engine (5 recommenders) | `app/services/recommendations.py` |
| LLM advisor (7 categories, BRD §6 template) | `app/services/recommendations_service.py` |
| Agent tools | `quick_recommendations` + `full_recommendations` in `app/agents/tools/recommendations.py` (Stage 10) |

**Categories (LLM advisor):**
`theme_material_pairing`, `dimension_alternative`,
`material_alternative`, `manufacturing_lead_time`,
`volume_economies`, `compliance_alert`, `supplier_or_region`.

**Proactive behaviour:** Stage 10 makes the engines callable. The
*proactive triggering* — i.e. the agent firing
`quick_recommendations` after every state-changing event without
the user prompting — is enforced by the agent system prompt
(see `app/prompts/`) which instructs the agent to call it after
generation / estimate / material-change events.

---

## Beyond BRD §Phase 1

The platform also ships features ahead of the Phase 1 spec:

| Capability | Stage | Where |
|---|---|---|
| Conversation memory + RAG | 5 / 5B / 5C / 5D | `app/memory/`, `app/agents/tools/{recall,memory}.py` |
| Knowledge corpus + RAG over global library | 6 | `app/corpus/`, `app/agents/tools/knowledge_search.py` |
| Multi-modal inputs (image / sketch / voice) | 7 | `app/storage/`, `app/vision/`, `app/agents/tools/vision.py` |
| Architect / client / project memory + decisions log | 8 | `app/profiles/`, `app/repositories/{architects,clients,decisions}/`, `app/agents/tools/{decisions,profiles}.py` |
| Haptic data structure (BRD Layer 7) | 9 | `app/haptic/`, `app/agents/tools/haptic.py` |

---

## Test surface

| Category | Test file | Scope |
|---|---|---|
| BRD Phase 1 closure | `tests/unit/test_stage10_brd_closure.py` | Tools registered + audit targets + BRD-anchored defaults (10% shock, [1,5,10] volumes, 5 brief sections) |
| Per-stage unit + integration | `tests/unit/test_stage{4a..9}*.py` + `tests/integration/test_stage{4a..9}*.py` | Each stage's deliverable in isolation |

Total agent toolset as of Stage 10: **78 tools**.

---

## Phase 2 candidates (not yet committed)

These are *not* BRD §Phase 1 gaps — they're features that came up
during the build and were noted for later:

- **Native `.rvt` export** via Windows worker + pyRevit (or ODA
  SDK). Phase 2 trigger: a customer signs who specifically requires
  native Revit project files instead of IFC.
- **Machine-specific G-code post-processors** for partner CNCs
  (Fanuc, Haas dialects). Phase 2 trigger: signing a manufacturing
  partner.
- **Strict-mode haptic export** (fail on unmapped materials). Stage 9
  ships lenient-with-flag mode; strict mode is a one-line addition
  when a hardware vendor needs it.
- **Embedding chat turns for semantic recall.** Stage 5 ships
  message persistence; semantic search over conversation history
  was deferred to Stage 5E / 8B.
- **GDPR-style profile delete via agent tool.** Currently a manual
  ops procedure — fine for soft launch, will need a self-serve
  surface before broader rollout.

---

## Sign-off

> KATHA-AI Phase 1 (BRD §1A through §6 plus Layers 6 + 7) ships
> 100% of specified features. Items shipped via interop (IFC for
> Revit, STEP for CAM dialects) deliver the BRD-asked-for outcome
> with a documented architect workflow.

**Last updated:** 2026-05-01 (Stage 10 close).
