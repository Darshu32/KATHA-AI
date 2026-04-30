# Agent Tool Catalog

> **Audience:** future-you adding tools, debugging agent behavior, or
> reviewing what the LLM can do.

---

## How tools work

Every tool is an async function decorated with `@tool` from
`app.agents.tool`. The decorator:

1. Auto-generates a JSON schema from the Pydantic input model.
2. Registers the tool in the global `REGISTRY` at import time.
3. Wraps invocation with timeout, audit logging, and error envelope.

The agent loop reads `REGISTRY.definitions_for_llm()` at session
start and hands them to Anthropic Claude as the available toolset.

See `docs/agents/architecture.md` for the lifecycle of one user
message and the SSE streaming protocol.

---

## Stage 2 — Cost engine (1 tool)

| Tool | Purpose |
|---|---|
| `estimate_project_cost` | Compute parametric cost breakdown (material + labor + overhead). Records an immutable `pricing_snapshot_id` for replay. Wraps Stage 1's DB-backed cost engine. |

---

## Stage 4A — Knowledge / compliance lookups (15 tools)

All read-only. Each tool's output includes `source_section`
(e.g. *"NBC 2016 Part 4 §3.2"*) where applicable so the agent can
cite its sources.

### Themes (2)

| Tool | Purpose |
|---|---|
| `lookup_theme` | Fetch the parametric rule pack for a theme by slug or alias. Returns palette, hardware, ergonomic targets, signature moves, dos/don'ts. |
| `list_themes` | List every published theme (slug + display name + era). |

### Clearances + space (3)

All return a status envelope (`ok` / `warn_low` / `warn_high` / `unknown`)
with the cited NBC/BRD source clause.

| Tool | Purpose |
|---|---|
| `check_door_width` | Validate a door width against NBC clearance rules. |
| `check_corridor_width` | Validate corridor minimum width per NBC. |
| `check_room_area` | Validate room area against BRD/NBC space-planning standards. |

### Codes (4)

| Tool | Purpose |
|---|---|
| `check_room_against_nbc` | Full NBC India minimum-room-dimensions check (area + short side + height) in one call. Returns every violation. |
| `get_iecc_envelope` | Fetch IECC envelope U-value targets (W/m²K) for walls + roof at a given international climate zone. |
| `lookup_climate_zone` | Get the NBC India climate-zone design strategy (orientation, glazing, U-targets, HVAC, passive priorities). Alias-tolerant. |
| `check_structural_span` | Sanity-check a span against typical limits for the material (IS 456 / IS 800 / IS 883). |

### Manufacturing (4)

| Tool | Purpose |
|---|---|
| `lookup_tolerance` | BRD ±mm tolerance for a manufacturing category. |
| `lookup_lead_time` | (weeks_low, weeks_high) lead-time band for a manufacturing category. |
| `lookup_joinery` | Full joinery spec (strength, difficulty, use, tolerance) for a wood-joining method. |
| `list_qa_gates` | The 5 BRD-canonical QA stages in order (material → dimension → finish → assembly → safety). |

### Ergonomics (2)

| Tool | Purpose |
|---|---|
| `check_ergonomic_range` | Validate a single furniture dimension against BRD §1C ergonomic ranges. |
| `lookup_ergonomic_envelope` | Fetch the full ergonomic envelope for a furniture item — every dimension as a [low, high] mm range. |

---

## How the agent uses them

Example architect query:
> *"What size kitchen will work for an 800 sqft Bangalore flat? And is a 1.5m corridor enough?"*

Sequence the agent might run:

```
1. check_room_area      (room_type=kitchen, area_m2=8.5, segment=residential)
                        → ok / warn_low / cite NBC Part 3
2. check_corridor_width (segment=residential, width_mm=1500)
                        → ok / cite BRD circulation
3. lookup_climate_zone  (zone=temperate)
                        → returns Bangalore design strategy
                        → agent surfaces glazing + HVAC tips
```

All three calls happen in parallel inside one agent turn (Stage 5
parallelisation pending). Final response cites every source clause.

---

## Stage 4B — MEP sizing (8 tools)

Wraps Stage 3C's `mep_sizing` helpers. Composite tools answer the
common architect question in one call; primitives cover follow-up
drills.

### HVAC (2)

| Tool | Purpose |
|---|---|
| `size_hvac_room` | One-shot HVAC sizing for a room: ACH → CFM → tonnage → equipment shortlist. The first tool to call when a user asks "what AC do I need". Returns BTU/hr + kW thermal too. |
| `size_duct` | Pick a standard round-duct diameter for a CFM (≈4 m/s branch velocity). |

### Electrical (2)

| Tool | Purpose |
|---|---|
| `size_lighting` | Fixture count to hit a lux target for an area + ambient circuit count from power density. LLF 0.8 + MF 0.7 folded in. |
| `estimate_outlets` | General-outlet count + task zones for a room based on perimeter (BIS / IS 732 + studio practice). |

### Plumbing (3)

| Tool | Purpose |
|---|---|
| `summarize_water_supply` | Roll up a fixture list to total WSFU (cold + hot + total), Hunter's-curve GPM, LPM, and main supply pipe size. The composite plumbing entry point. |
| `size_drain_pipe` | Pick a drain-pipe size (mm) for a total DFU per IPC / NBC Part 9. |
| `size_vent_stack` | Pick a vent-stack diameter for DFU + developed length per IPC 906.1. |

### System cost (1)

| Tool | Purpose |
|---|---|
| `mep_system_cost_estimate` | Order-of-magnitude per-m² cost band for major MEP systems (HVAC / electrical / plumbing / fire / low-voltage) — early-stage budget check before the full cost engine runs. Distinct from Stage 2's `estimate_project_cost`. |

---

## Stage 4C — Cost extensions (2 tools)

Orchestration tools that wrap Stage 2's `estimate_project_cost` engine
with multi-run logic. Both still call the LLM (one call per scenario),
so each tool caps the variant count at the input-schema layer to
prevent runaway spend.

| Tool | Purpose |
|---|---|
| `compare_cost_scenarios` | Run 2–4 named scenarios side-by-side. Each scenario can be a fresh request *or* a snapshot replay. Returns deltas vs the first scenario, plus cheapest / most-expensive labels and the spread. Use when the user asks "what if we did X vs Y" — mass-market vs luxury, Mumbai vs Bangalore, simple vs complex joinery. |
| `cost_sensitivity` | Hold a base request constant, vary **one** parameter (`city` / `complexity` / `market_segment` / `hardware_piece_count` / `theme`) across 2–5 values, return per-variant deltas + elasticity. Numeric parameters get a `% per unit` elasticity number; categorical ones do not. |

Each variant's `pricing_snapshot_id` is preserved so the architect can
drill into any single variant later via the standard cost route.
Partial failures degrade gracefully: a single failing variant is
labelled in the output with an `error`, the rest still report.

---

## Stage 4D — Spec generation (3 tools)

LLM-heavy authors that wrap the BRD-grade spec services. Each call
issues one OpenAI round-trip; per-tool timeout is 90 s. All three are
**write tools** — every successful call records an `AuditEvent` so
the project log carries the spec author + parameters.

| Tool | Purpose |
|---|---|
| `generate_material_spec` | Authors the BRD 3B Material Specification Sheet — primary structure, secondary materials, hardware, upholstery, finishing, cost summary. Theme slug is required (palette grounds every decision). Returns the full sheet plus `validation_passed` + per-flag failure list. |
| `generate_manufacturing_spec` | Authors the BRD 3C Manufacturing Specification — woodworking precision + joinery, metal fabrication notes, upholstery assembly, QA gates, lead time, MOQ. Theme slug required. |
| `generate_mep_spec` | Authors the BRD 3D MEP Specification for one room — HVAC sizing (ACH, CFM, ductwork, equipment tonnage + BTU), electrical (lighting circuits, panel, outlet count), plumbing (DFU, drain + vent), indicative cost. Requires `room_use_type` + `dimensions` (length/width/height in m). |

Each output preserves the **full structured spec** under
`material_spec_sheet` / `manufacturing_spec` / `mep_spec` so
follow-up agent turns can drill into any section without
re-running the LLM. The tool-layer summary surfaces:

- `id`, `name`, theme/city/use_type provenance
- `validation_passed` (bool) + `validation_failures` (list of flag names)
- `sections_authored` (top-level keys present in the spec)

When the underlying service raises (`MaterialSpecError`,
`ManufacturingSpecError`, `MEPSpecError`) — e.g. unknown theme,
unknown room use, unknown plumbing fixture — the tool returns
the standard structured-error envelope with the original message.

---

## Stage 4E — Drawing generation (5 tools)

LLM-heavy authors that wrap the BRD-grade drawing services. Each call
issues one OpenAI round-trip **plus** an in-process SVG render. The
output carries both: the structured drawing spec the LLM authored
*and* the rendered SVG. Per-tool timeout is 120 s. All five are
**write tools** with their own audit target.

| Tool | Purpose |
|---|---|
| `generate_plan_view_drawing` | Top-down plan — scale, key dimensions, section reference lines, material zones with hatch keys, sheet narrative. Pass `design_graph` (Stage 3A) for room-scale plans, `parametric_spec` for piece-scale. |
| `generate_elevation_view_drawing` | Front/side elevation of a furniture piece (or a room wall) — height + width dimensions, ergonomic targets called out, hardware callouts, hatch keys. Pass a `piece` (preferred) or a `design_graph`. |
| `generate_section_view_drawing` | Cut-through section — layer stack (frame / foam / upholstery / finish), joinery + tolerances, reinforcement points. Configure `cut_label` (default `"A-A"`) and `view_target` (default `through_seat`). |
| `generate_detail_sheet_drawing` | Multi-cell zoom-in sheet — joints, edges, seams, hardware, material transitions. Each cell carries scale + tolerance + a one-line note. The LLM picks 4–9 cells across at least 3 detail types. |
| `generate_isometric_view_drawing` | Full-piece iso (`view_mode="iso"`) or perspective sheet — overall form, parts breakdown, optional **exploded view** (`explode_enabled=true`) for assembly briefs. |

### Output shape (shared across all 5)

```python
{
  "id": "elevation_view",       # canonical drawing id
  "name": "Elevation View",
  "format": "svg",
  "theme": "scandinavian",
  "validation_passed": true,
  "validation_failures": [],    # names of bool flags that returned False
  "spec": { ... },              # the full structured drawing spec
  "svg": "<svg ... />",         # the rendered markup
  "meta": { ... }               # per-drawing stat keys (dim counts, hardware count, ...)
}
```

### `ElevationPieceInput` — shared by 4 of 5 tools

The elevation / section / detail / isometric tools all take an
optional nested `piece` describing the furniture archetype:

| Field | Purpose |
|---|---|
| `type` | Furniture slug — drives ergonomic envelope lookup. Default `"lounge_chair"`. |
| `dimensions_mm` | Optional `{length, width, height}` in mm. Falls back to ergonomic mid-points. |
| `ergonomic_targets_mm` | Optional `seat_height_mm`, `back_height_mm`, etc. — overrides BRD defaults. |
| `material_hatch_key` | Hatch vocabulary key for the primary surface. |
| `leg_base_hatch_key` | Hatch vocabulary key for the leg / base. |

Canvas dims are capped at the input layer (`480 ≤ width/height ≤ 2400`) so
the LLM can't request a 10000×10000 SVG.

When the underlying service raises (`PlanViewError`, `ElevationViewError`,
etc.) — e.g. unknown theme, missing piece envelope, malformed LLM JSON —
the tool returns the standard structured-error envelope.

---

## Stage 4F — Diagram generation (8 tools)

LLM-heavy authors that wrap the BRD Layer 2B diagram services. Each
call issues one OpenAI round-trip **plus** an in-process SVG render
(deterministic base from the design graph + LLM-driven annotations).
Output shape is identical to Stage 4E drawings — uniform
`DiagramOutput` with `id`, `name`, `format="svg"`, `theme`,
`validation_passed`, `validation_failures`, `spec`, `svg`, `meta`.

| Tool | BRD ref | Purpose |
|---|---|---|
| `generate_concept_diagram` | 2B #1 | **Concept Transparency** — material/form relationship, functional zones, signature moves, emphasis points. Use for client kick-off. |
| `generate_form_diagram` | 2B #2 | **Form Development** — four-stage evolution (volume → grid → subtract → articulate) with theme signature moves per stage. |
| `generate_volumetric_diagram` | 2B #3 | **Volumetric Hierarchy** — vertical × horizontal read: silhouette, weight distribution, space allocation, stacking logic. |
| `generate_volumetric_block_diagram` | 2B #4 | **Volumetric (Block)** — 3D block read with masses, voids, slicing strategy. Use for massing alternatives. |
| `generate_design_process_diagram` | 2B #5 | **Design Process** — step-by-step decision narrative + rejected alternatives. Uniquely accepts `architect_brief` to anchor the cascade. |
| `generate_solid_void_diagram` | 2B #6 | **Solid vs Void** — solid % vs void %, weight pattern, breathing room, watch-outs against circulation minima. |
| `generate_spatial_organism_diagram` | 2B #7 | **Spatial Organism** — body-in-space: interaction touchpoints, movement choreography, usage patterns. |
| `generate_hierarchy_diagram` | 2B #8 | **Hierarchy** — three rankings (visual / material / functional) with emphasis rules per tier. |

### Common request fields

All 8 tools share the same core inputs:

| Field | Purpose |
|---|---|
| `theme` | **Required** theme slug — palette grounds every annotation. |
| `design_graph` | Stage 3A graph (rooms, walls, objects). Preferred input for room-scale reads. |
| `parametric_spec` | Optional — used as fallback geometry when `design_graph` is absent. |
| `project_summary` | Free-text context the LLM weaves into the narrative. |
| `canvas_width`, `canvas_height` | Capped at the input layer (`320–2400` × `240–2200`). |

`generate_design_process_diagram` adds one extra optional field —
`architect_brief: dict` — so the LLM can show how brief → decisions →
form cascaded.

### Validation

Some services emit a `validation: {flag: bool, ...}` block; others
don't. The wrapper's `_summarise_validation` helper returns
`(True, [])` when the block is missing — so `validation_passed` is
never falsely negative.

When the underlying service raises (`ConceptDiagramError`,
`FormDiagramError`, etc.) — typically unknown theme or malformed
LLM JSON — the tool returns the standard structured-error envelope.

---

## Stage 4G — Generation pipeline (5 tools)

The first tools that **mutate persisted state**. Every Stage 4G tool
reads `ctx.project_id` from the agent context — it refuses to run
without a project in scope. The 3 LLM-heavy generation tools all
record an audit event under `target_type="design_graph"`; the 2
read tools have no audit footprint.

| Tool | Purpose |
|---|---|
| `generate_initial_design` | Run the full initial-generation pipeline from a free-text prompt. AI builds the structured design graph, persists it as v1, computes an estimate. Use when the user opens a fresh project with "design me X". |
| `apply_theme` | Re-skin the latest design-graph version under a new theme. Persists a new version with `change_type="theme_switch"`. Toggle `preserve_layout` (default `True`) to keep dimensions / positions and just swap materials, or to allow the AI to reshape. |
| `edit_design_object` | Edit a single object via free-text prompt — "make this 1.8 m long", "swap to walnut". Persists a new version with `change_type="prompt_edit"` and records `changed_object_ids`. |
| `list_design_versions` | Read-only — return every persisted version for the current project (newest first). The agent uses this to answer "show me my design history" or to find a `version_id` to drill into. |
| `validate_current_design` | Read-only — run the BRD/NBC knowledge validator on the latest version. Returns errors, warnings, suggestions covering room area, ergonomics, NBC compliance, theme palette drift, door clearances, structural span limits, MEP, manufacturing. Toggle `segment="commercial"` for non-residential thresholds. |

### `GenerationOutput` — shared shape across the 3 write tools

```python
{
  "project_id": "test-project-123",
  "version": 2,
  "version_id": "ver-2",
  "change_type": "theme_switch",
  "change_summary": "Theme switched to scandinavian",
  "status": "completed",
  "graph_summary": {                # slim view for LLM reasoning
    "room_type": "living_room",
    "room_dimensions_m": {"length": 5.0, "width": 4.0, "height": 2.7},
    "object_count": 12,
    "object_types": ["sofa", "coffee_table", "lamp"],
    "material_count": 6,
    "style_primary": "scandinavian"
  },
  "estimate_summary": {"total": 280000, "currency": "INR", "summary": "..."},
  "full_graph_data": { ... },       # full graph for chaining drawing/diagram tools
  "changed_object_ids": ["obj-1"]   # populated by edit_design_object only
}
```

The `full_graph_data` field is intentionally preserved so the agent
can chain a Stage 4E drawing or 4F diagram tool with the freshly-saved
graph in the same turn — no DB re-fetch needed.

### Project-scope guard

Every Stage 4G tool calls `_require_project(ctx)` first; if
`ctx.project_id` is unset, it returns a structured `ToolError` with
the message `"No project_id on the agent context..."`. The agent
loop is responsible for setting `ToolContext.project_id` for the
current chat. This prevents the LLM from accidentally redirecting
calls to a different user's project.

### Service-error translation

`run_initial_generation` / `run_theme_switch` / `run_local_edit`
raise `ValueError` (e.g. "no versions found") and `RuntimeError`
(orchestrator failures); both surface as the standard
structured-error envelope. Validation errors at the schema layer
(short prompt, missing required field) return the
`validation_error` envelope without ever touching the pipeline.

---

## Stage 4H — Imports / exports (8 tools)

Eight tools that move designs in and out of the platform. Mix of read,
deterministic-write, and LLM-heavy advisor calls.

### Discovery (no audit, no project scope)

| Tool | Purpose |
|---|---|
| `list_export_formats` | Return the 15 registered exporters (pdf / docx / xlsx / pptx / html / dxf / obj / gltf / fbx / ifc / step / iges / gcode / cam_prep / geojson) grouped by family with capability metadata — best_for, compatible_with, preconditions, precision. |
| `list_import_formats` | Return every file extension the deterministic importers can parse — pdf, png/jpg/jpeg, dxf/dwg, step/stp/iges, obj/fbx/gltf, csv, xlsx/xls, docx, txt/md. |
| `list_export_recipients` | Return the 10 canonical recipient roles (client, architect, interior_designer, fabricator, cnc_shop, rendering_studio, bim_consultant, project_manager, structural_engineer, mep_consultant) annotated with their preferred format families. |

### Project-scoped read

| Tool | Purpose |
|---|---|
| `build_spec_bundle_for_current` | Assemble the spec bundle (meta + material + manufacturing + mep + cost) from the current project's latest design-graph version. Surfaces a `bundle_status` flag dict — what's ready, what isn't — that drives `generate_export_manifest`. |

### Project-scoped write (audit `target_type="export_bundle"`)

| Tool | Purpose |
|---|---|
| `export_design_bundle` | Run a registered exporter on the current project's bundle. Returns `content_type`, `filename`, `size_bytes`, and (when ≤ 32 KB) a base64-encoded `content_base64`. Larger payloads set `inline_bytes_omitted=true`; the agent UI fetches via a side-channel. |

### Stateless deterministic

| Tool | Purpose |
|---|---|
| `parse_import_file` | Decode base64 file content + run the deterministic importer matched to the file extension. Returns the structured `ImportPayload` shape (format, filename, size_bytes, summary, extracted, warnings). No LLM, no DB write. |

### LLM-heavy advisors (audit)

| Tool | Audit | Purpose |
|---|---|---|
| `generate_import_manifest` | `import_manifest` | Author the LLM ingestion manifest from a list of pre-parsed imports — extractions, conflicts vs existing brief / graph, merge plan. Cap of 20 imports per call. |
| `generate_export_manifest` | `export_manifest` | Author the LLM export-advisor manifest — per-format capability sheet, per-recipient recommendations, primary handoff format. Reads from `bundle_status` (typically piped from `build_spec_bundle_for_current`). |

### Bytes handling — the 32 KB threshold

`export_design_bundle` is the only tool that produces real file bytes.
The agent's context window is precious, so:

- **Files ≤ 32 KB**: base64 inlined into `content_base64` so the
  agent can offer a download immediately.
- **Files > 32 KB**: `content_base64=null`, `inline_bytes_omitted=true`,
  `inline_bytes_limit=32768`. The export still ran successfully — the
  agent UI is responsible for fetching the bytes via a side-channel
  keyed on `project_id` + `filename`.

This keeps a 5 MB FBX export from blowing up the LLM context.

### Workflow chain

A typical export interaction:

```
1. list_export_recipients     → user picks "fabricator"
2. build_spec_bundle_for_current → bundle_status reflects readiness
3. generate_export_manifest   → LLM picks IFC + STEP + PDF for fabricator
4. export_design_bundle       → run each exporter, return bytes
```

A typical import interaction:

```
1. list_import_formats        → confirm the file extension is supported
2. parse_import_file          → deterministic extraction (no LLM)
3. generate_import_manifest   → LLM merges into existing brief / graph
```

---

## Stage 4 — complete

**Cumulative running total: 55 tools** across Stage 2 + Stages 4A–4H.
Target was ~50 by end of Stage 4 — landed at 55. The agent now has a
complete inner loop: design → render drawings → render diagrams →
spec out → cost it → validate → theme-switch → edit → re-validate →
import / export.

| Stage | Tools | Theme |
|---|---|---|
| 2 | 1 | Cost engine pilot |
| 4A | 15 | Knowledge / compliance lookups |
| 4B | 8 | MEP sizing |
| 4C | 2 | Cost extensions (sensitivity, scenario compare) |
| 4D | 3 | Spec generation (material / manufacturing / MEP) |
| 4E | 5 | Drawing generation (plan / elevation / section / detail / iso) |
| 4F | 8 | Diagram generation (BRD 2B — 8 types) |
| 4G | 5 | Generation pipeline (initial / theme / edit / list / validate) |
| 4H | 8 | Imports / exports |

Stage 5 begins the **agent runtime work** — multi-tool orchestration,
parallel tool calls, conversation memory, vector search over project
artefacts.

---

## Anti-goals (what tools do NOT do)

- **Tools never crash the agent.** Bad inputs → validation envelope.
  Tool errors → structured error dict the LLM can read and recover from.
- **Tools never write outside their declared scope.** Read tools have
  no audit footprint; write tools declare `audit_target_type` and
  emit one `AuditEvent` per call.
- **Tools never call other tools directly.** The agent loop chains
  them. Tools that need shared state read it from `ToolContext.state`.

---

## Adding a new tool

Three steps. ~30 minutes per tool.

1. **Write it.** Pydantic input + output models, async function with
   `(ctx: ToolContext, input: <Input>) -> <Output>`, decorated with
   `@tool(name=..., description=..., timeout_seconds=..., audit_target_type=...)`.
2. **Register it.** Add `from app.agents.tools import <module> as _<module>  # noqa: F401`
   to `app/agents/tools/__init__.py` and append the module reference
   to `_REGISTERED_MODULES`.
3. **Test it.** Add the tool name to `STAGE_NX_TOOLS` in the registry
   test, plus an integration test that invokes it through `call_tool`.

Conventions:

- **Output models always succeed** — bad inputs produce
  `status="unknown"` envelopes or `found=false` flags rather than
  raising.
- **Source citation is mandatory** for compliance tools — output
  includes `source_section` where the underlying DB row provides one.
- **Description is product code, not config** — it's what the LLM
  reads to decide when to call. Treat changes as reviewable PRs.
