# Stage 9 — Haptic Data Structure (BRD Layer 7)

> Status: shipped in Stage 9. Hardware integration (driver layer)
> remains a Phase-2 deliverable; this document is the contract
> Phase-2 vendors read.

## Purpose

KATHA prepares **data for the haptic layer** without requiring
hardware to exist yet. Any saved design in the system can produce
a complete haptic export — a single JSON document the haptic
driver consumes end-to-end. When the hardware ships, the
integration is a *driver-side* problem: the data layer is ready.

This is the spec for that JSON document. It is also the contract
for engineers extending the haptic catalog (new materials, new
object types, new feedback rules) via future migrations.

## Architecture at a glance

```
┌────────────────────────┐
│ design_graph_versions  │  ← existing — design graph snapshot (JSONB)
└──────────┬─────────────┘
           │ graph_data (rooms, objects, materials, dimensions)
           ▼
┌────────────────────────┐
│ app.haptic.exporter    │  ← Stage 9 — assembles the payload
└──────────┬─────────────┘
           │ reads
           ▼
┌────────────────────────┐
│ haptic catalog (6 tbls)│  ← Stage 9 — seed migration 0020
│   haptic_textures      │
│   haptic_thermal       │
│   haptic_friction      │
│   haptic_firmness      │
│   haptic_dimension_…   │
│   haptic_feedback_…    │
└────────────────────────┘
           │
           ▼
       ┌─────────┐
       │ payload │ ← consumed by hardware driver
       └─────────┘
```

## The six catalog tables

Materials are referenced by **string keys** (e.g. `walnut`,
`leather`). There is no foreign key to a materials table — the
design graph is JSONB and stores the same string keys. The catalog
is a parallel lookup indexed by the same key.

### `haptic_textures` — one row per material

| Column | Type | Notes |
|---|---|---|
| `id` | String(32) | PK (uuid) |
| `name` | String(200) | Human-readable, e.g. "Walnut grain" |
| `code` | String(100) UNIQUE | Stable identifier for hardware drivers, e.g. `walnut_grain_001` |
| `material_id` | String(100) INDEX | Material key, e.g. `walnut` |
| `signature_data` | JSONB | Parametric texture description (no bitmaps) |

`signature_data` shapes per pattern type:

```jsonc
// "linear_grain" — woods
{ "pattern": "linear_grain",
  "grain_freq_per_cm": 6,         // ridges per cm along the grain
  "amplitude_um": 80,             // peak-to-trough in micrometres
  "direction": "with_grain" }

// "fine_pebble" — leather
{ "pattern": "fine_pebble",
  "amplitude_um": 50,
  "pebble_size_mm": 0.6 }

// "weave" — fabrics
{ "pattern": "weave",
  "thread_count_per_cm": 30,
  "amplitude_um": 30 }

// "smooth" — glass / brass
{ "pattern": "smooth",
  "amplitude_um": 0,
  "transparency": true }            // optional, glass only

// "linear_brush" — brushed metals
{ "pattern": "linear_brush",
  "amplitude_um": 5,
  "direction": "longitudinal" }

// "rough" — concrete
{ "pattern": "rough",
  "amplitude_um": 200,
  "aggregate_size_mm": 4 }
```

### `haptic_thermal` — perceived surface temperature

| Column | Type | Notes |
|---|---|---|
| `material_id` | String(100) UNIQUE | Material key |
| `temperature_celsius` | Float | Perceived against 22 °C ambient |
| `source` | Text | Citation for the value |

> **BRD anchors:** walnut → 28 °C, leather → 32 °C.

Temperatures reflect the *perceived* feel against skin —
low-thermal-effusivity materials (wood, leather) feel warm;
high-effusivity materials (steel, glass) feel cool. They do not
represent the material's actual temperature, which equals the
ambient room temperature.

### `haptic_friction` — static fingertip friction

| Column | Type | Notes |
|---|---|---|
| `material_id` | String(100) UNIQUE | Material key |
| `coefficient` | Float | Static μ vs. human fingertip |
| `condition` | String(64) | Default `dry_room_temp` |

> **BRD anchors:** wood → 0.35, leather → 0.40.

### `haptic_firmness` — pushback + perceived weight

| Column | Type | Notes |
|---|---|---|
| `material_id` | String(100) UNIQUE | Material key |
| `firmness_scale` | String(32) | One of `soft` \| `medium` \| `firm` (DB CHECK) |
| `density` | Float | Bulk density kg/m³ |

The arm uses `firmness_scale` to set pushback when the user presses
a virtual surface, and `density` × volume to compute perceived
weight when an object is lifted.

### `haptic_dimension_rules` — per object type

| Column | Type | Notes |
|---|---|---|
| `object_type` | String(100) UNIQUE | e.g. `chair`, `dining_table`, `door` |
| `adjustable_axes` | JSONB | List of axis names the user can tweak |
| `ranges` | JSONB | Per-axis `{min_mm, max_mm, step_mm}` |
| `feedback_curve` | JSONB | `{kind, constraints[]}` describing how a change propagates |

Example row (chair, BRD-anchored seat-height range 18–22 in):

```jsonc
{
  "object_type": "chair",
  "adjustable_axes": ["seat_height", "seat_depth", "seat_width"],
  "ranges": {
    "seat_height": {"min_mm": 457, "max_mm": 559, "step_mm": 10},
    "seat_depth":  {"min_mm": 380, "max_mm": 480, "step_mm": 10},
    "seat_width":  {"min_mm": 400, "max_mm": 520, "step_mm": 10}
  },
  "feedback_curve": {
    "kind": "linear_with_constraints",
    "constraints": ["maintain_back_to_seat_ratio:1.6_to_2.0"],
    "notes": "Adjusting seat_height drags armrest height proportionally."
  }
}
```

### `haptic_feedback_loops` — declarative trigger → response rules

| Column | Type | Notes |
|---|---|---|
| `rule_key` | String(120) UNIQUE | Stable namespaced id, e.g. `chair.seat_height.cost_per_cm` |
| `trigger` | JSONB | Structured "what change activates the rule" |
| `response` | JSONB | Structured "what consequence the rule emits" |
| `formula` | Text | Human-readable formula (BRD calls these out) |

The BRD examples land verbatim in seed:

| BRD example | Seed `rule_key` |
|---|---|
| "When height changes by 1cm, cost changes by ₹X" | `chair.seat_height.cost_per_cm` (slope ₹50/cm), `dining_table.height.cost_per_cm` (₹80/cm), `desk.height.cost_per_cm` (₹70/cm) |
| "When material changes from walnut to oak, cost -₹Y" | `material.swap.walnut_to_oak` (delta -₹1500) and inverse |
| "Proportions maintained within design intent" | `proportion.chair.back_to_seat_ratio` (ratio ∈ [1.6, 2.0]), `proportion.door.aspect_ratio` (ratio ∈ [2.0, 3.0]) |

`response.kind` ∈ {`linear`, `step`, `proportional`}. Hardware
drivers branch on this value.

## The export payload

Produced by `app.haptic.exporter.build_haptic_payload()` and
returned by the agent tool `export_haptic_payload`. Schema below
is **versioned** — bump `HAPTIC_SCHEMA_VERSION` (currently
`9.0.0`) on breaking changes.

```jsonc
{
  // ── Envelope ──────────────────────────────────────────────────
  "schema_version": "9.0.0",        // payload structure version
  "catalog_version": "2026.05.01",  // catalog data version
  "graph_version_id": "<uuid>",
  "project_id": "<uuid>",
  "design_version": 3,              // sequential within project
  "generated_at": "2026-05-01T12:34:56.789+00:00",

  // ── Bucket 1 — Dimension data (BRD §Layer 7) ──────────────────
  "dimensions": {
    "rooms": [
      {
        "id": "room-1",
        "name": "living",
        "width_mm":  5000.0,
        "depth_mm":  4000.0,
        "height_mm": 2700.0
      }
    ],
    "objects": [
      {
        "id": "chair-1",
        "type": "chair",
        "material_key": "walnut",
        "dimensions_mm": { "width": 500.0, "depth": 500.0, "height": 900.0 },
        "position_mm":   { "x": 1000.0, "y": 0.0, "z": 1000.0 }
      }
    ]
  },

  // ── Bucket 2 — Material haptic properties (BRD §Layer 7) ──────
  "materials": [
    {
      "key": "walnut",
      "texture": {
        "code": "walnut_grain_001",
        "name": "Walnut grain",
        "signature_data": {
          "pattern": "linear_grain",
          "grain_freq_per_cm": 6,
          "amplitude_um": 80,
          "direction": "with_grain"
        }
      },
      "thermal":  { "temperature_celsius": 28.0,
                    "source": "BRD §Layer 7; …" },
      "friction": { "coefficient": 0.35, "condition": "dry_room_temp" },
      "firmness": { "firmness_scale": "firm", "density_kg_m3": 660.0 }
    }
  ],

  // ── Bucket 3 — Interaction parameters (BRD §Layer 7) ──────────
  "interactions": [
    {
      "object_id": "chair-1",
      "object_type": "chair",
      "adjustable_axes": ["seat_height", "seat_depth", "seat_width"],
      "ranges": { /* same shape as catalog */ },
      "constraints": ["maintain_back_to_seat_ratio:1.6_to_2.0"],
      "feedback_curve_kind": "linear_with_constraints"
    }
  ],

  // ── Bucket 4 — Feedback loops (BRD §Layer 7) ──────────────────
  "feedback_loops": [
    {
      "rule_key": "chair.seat_height.cost_per_cm",
      "trigger":  { "object_type": "chair",
                    "axis": "seat_height",
                    "delta_unit": "cm" },
      "response": { "target": "cost_inr",
                    "kind": "linear",
                    "slope_per_unit": 50 },
      "formula":  "ΔCost(INR) = 50 × ΔSeatHeight(cm)"
    }
  ],

  // ── Workspace metadata (arm-reach planning) ───────────────────
  "workspace": {
    "max_width_mm":  5000.0,
    "max_depth_mm":  4000.0,
    "max_height_mm": 2700.0,
    "room_count": 1
  },

  // ── Validation block ──────────────────────────────────────────
  "validation": {
    "all_materials_mapped": true,
    "requested_materials":  ["walnut", "oak"],
    "mapped_materials":     ["walnut", "oak"],
    "fallback_materials":   [],
    "missing_object_types": [],
    "warnings": []
  }
}
```

## Versioning contract

Two independent version strings ride on every payload. Hardware
drivers MUST validate both before consuming:

| Version | Semantics | Bumps when |
|---|---|---|
| `schema_version` | Payload structure (semver) | Adding/removing top-level keys, changing field types |
| `catalog_version` | Catalog seed data | Material values change, new material added, new object type added |

The current values live in `app/haptic/__init__.py` and ship with
the codebase, not the database — every payload reads from the same
source of truth.

## Fallback policy

Per BRD §Layer 7: **every material in the design graph must have a
haptic mapping (or fall back to the `generic` profile)**.

Implementation:

1. The exporter looks up the material key in the catalog.
2. If a complete profile exists → embed it.
3. If not → embed the `generic` profile with a `texture.fallback_for`
   field stamping the original key. The validator records the key
   in `validation.fallback_materials`.
4. Exports never fail on unmapped materials. Vendors wanting
   strict behaviour can branch on `validation.all_materials_mapped`.

The `generic` profile is itself a real catalog row (key:
`generic`). If it goes missing the validator emits a warning
suggesting the seed migration be re-run.

## Owner / project scope

The agent tool `export_haptic_payload` operates only on design-graph
versions belonging to `ToolContext.project_id`. Cross-project
access (architect A asking for architect B's design) returns the
same `ToolError` shape whether the row exists under another project
or not at all — no existence leakage.

## Audit

Every successful call writes one `AuditEvent` row with:

- `target_type` = `haptic_export`
- `target_id` = `project_id`
- `after.tool` = `export_haptic_payload`
- `after.elapsed_ms`, `after.input`, `after.output_summary_keys`

Use `target_type=haptic_export` to filter the audit log for
"every haptic export ever generated for project X."

## Extending the catalog

To add a material:

1. Edit `app/haptic/seed.py` — append to `_MATERIALS` (with all
   four property tuples filled).
2. Create a new migration `00NN_haptic_catalog_…py` that inserts
   the new rows into the four property tables. Do NOT edit
   migration 0020 — its rows are already in production.
3. Bump `HAPTIC_CATALOG_VERSION` in `app/haptic/__init__.py`.
4. Add a regression test in `tests/unit/test_stage9_haptic.py`
   pinning the new material's BRD-anchored values (if any).

To add an object type or feedback rule, the same pattern applies
to `_DIMENSION_RULES` / `_FEEDBACK_LOOPS`.

## Test surface

| Test | What it locks |
|---|---|
| `tests/unit/test_stage9_haptic.py` | Seed values match BRD anchors; texture codes unique; every material has all four property rows; validator coverage outcomes |
| `tests/integration/test_stage9_haptic.py` | Real Postgres + alembic; payload has all four BRD buckets; walnut → 28 °C round-trips; unmapped material → generic fallback; cross-project access errors out; tool writes haptic_export AuditEvent |

## Deferred to Stage 9B

These were explicitly **out of scope** for Stage 9 to keep the
surface small and the catalog trustworthy:

- **Agent-authored materials.** The catalog is migration-only for
  now. Architects cannot register custom materials via the agent.
- **Persisted export artefacts.** Exports are returned inline by
  the tool; nothing is written to S3 / `haptic_export_artifacts`.
- **XML output.** BRD allows JSON/XML — only JSON ships in v1.
- **Strict / lenient modes.** BRD specifies a fall-back policy;
  the export is always lenient (with the substitution flagged).
  A future strict mode could fail exports with unmapped materials.
- **Live cost-engine snapshotting.** Feedback loops are static
  rules in the catalog. A future stage could compile them from
  the cost engine at export time.
- **Material swap option catalog.** "Walnut → oak is OK" rules
  are encoded as feedback loops, not as a separate swap catalog.
