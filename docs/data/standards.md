# Stage 3B / 3C / 3D / 3E — Building Standards Externalization

> **Audience:** future-you adding jurisdictional overrides, debugging
> compliance flags, or onboarding the compliance officer to the admin UI.

---

## What's externalised

**All nine** building-standard legacy modules — `clearances.py`,
`space_standards.py`, `mep.py`, `manufacturing.py`, `codes.py`,
`ibc.py`, `structural.py`, `climate.py`, and `ergonomics.py` — have
been merged into a single DB table: `building_standards`.

| Stage | Adds | Categories | Rows seeded |
|---|---|---|---|
| **3B** | Clearances + space requirements | `clearance`, `space` | ~50 |
| **3C** | HVAC + electrical + plumbing + system costs | `mep` | ~150 |
| **3D** | Tolerances + joinery + welding + lead times + MOQ + QA gates + process specs | `manufacturing` | ~45 |
| **3E** | NBC + IBC + ECBC + IECC + accessibility + fire safety + structural + climate + furniture ergonomics | `code` (+ extra `space` rows) | ~80 |

One table, five categories, jurisdictional overrides. One admin UI
covers all of compliance, building codes, and ergonomic reference.

---

## Schema

```
building_standards
├─ id                  uuid hex
├─ slug                "door_main_entry" / "bedroom" / etc.
├─ category            clearance | space | mep | code
├─ jurisdiction        india_nbc | international_ibc | maharashtra_dcr | …
├─ subcategory         door | corridor | stair | residential_room | …
├─ display_name        "Main Entry Door"
├─ notes               free text
├─ data                JSONB — the actual rule (varies per row)
├─ source_section      "NBC 2016 Part 4 §3.2"
├─ source_doc          NBC-2016 | IBC-2021 | BRD-Phase-1 | …
└─ <Stage-0 conventions>:
   deleted_at, version, is_current, previous_version_id,
   effective_from, effective_to, source, source_ref, created_by
```

**Logical key:** `(slug, category, jurisdiction)` — partial unique
index on `is_current AND NOT deleted` enforces "exactly one current
version per logical key".

---

## Data shapes

The `data` JSONB column varies by row but follows category-stable
patterns. Cost-engine prompts and validators rely on these shapes:

### Clearance — door / window
```json
{ "width_mm": [1000, 1200], "height_mm": [2100, 2400] }
```

### Clearance — corridor
```json
{ "min_width_mm": 800, "preferred_mm": 1000 }
```

### Clearance — stair
```json
{
  "rise_mm": [150, 200],
  "tread_mm": [250, 300],
  "min_width_mm": 900,
  "headroom_mm": 2100,
  "max_rise_run_rule": "2*rise + tread ~ 600-640mm"
}
```

### Clearance — circulation (single value)
```json
{ "clearance_mm": 600 }
```

### Clearance — egress (rule set)
```json
{
  "max_travel_distance_residential_m": 30,
  "max_travel_distance_office_unsprinklered_m": 45,
  "min_exit_count_over_50_occupants": 2,
  "dead_end_corridor_max_m": 6
}
```

### Space — residential / commercial / hospitality room
```json
{
  "min_area_m2": 9.0,
  "typical_area_m2": 12.0,
  "min_short_side_m": 2.7,
  "min_height_m": 2.7
}
```

---

## Jurisdictional overrides — how they work

Every project carries an implicit jurisdiction (default `india_nbc`).
When the agent or cost engine asks for a standard:

```python
from app.services.standards import resolve_standard

row = await resolve_standard(
    session,
    slug="corridor_residential",
    category="clearance",
    jurisdiction="maharashtra_dcr",
)
```

The resolver picks the most specific row available:

```
1. Look up (slug, category, jurisdiction='maharashtra_dcr')
2. If found → return it (jurisdiction-specific rule wins)
3. Else → look up (slug, category, jurisdiction='india_nbc')   ← BRD baseline
4. If found → return it
5. Else → None
```

This means seed data ships only the `india_nbc` baseline. State /
city overrides are added as additional rows with the same
`(slug, category)` but different `jurisdiction`. Admin updates via
REST — same versioning, same audit.

### Adding a Maharashtra DCR override

```bash
# Step 1: query the existing baseline to copy from
curl /admin/standards/clearance/corridor_residential

# Step 2: insert override directly via SQL (no admin endpoint for "create"
# yet — Stage 4+ adds this; for now seed via migration or direct SQL).
psql $DATABASE_URL <<SQL
INSERT INTO building_standards (
  id, slug, category, jurisdiction, subcategory,
  display_name, data, source_section, source_doc,
  version, is_current, effective_from, source
) VALUES (
  md5(random()::text),
  'corridor_residential', 'clearance', 'maharashtra_dcr', 'corridor',
  'Residential Corridor (Maharashtra DCR)',
  '{"min_width_mm": 1000, "preferred_mm": 1200}',
  'Maharashtra DCR 2034 — clause X',
  'Maharashtra-DCR-2034',
  1, TRUE, NOW(), 'admin:override'
);
SQL

# Step 3: verify
curl "/admin/standards/clearance/corridor_residential?jurisdiction=maharashtra_dcr"
```

After this, any project tagged Maharashtra DCR sees the 1000 mm
minimum; everywhere else sees the 800 mm baseline. Past compliance
checks reproduce because pricing snapshots / decision logs carry the
jurisdiction they used.

---

## Common operations

### Browse by category

```bash
GET /admin/standards?category=clearance
GET /admin/standards?category=space
GET /admin/standards?category=clearance&subcategory=stair
GET /admin/standards?category=space&jurisdiction=maharashtra_dcr
```

### Get one (without resolver fallback)

```bash
GET /admin/standards/clearance/door_main_entry
GET /admin/standards/space/bedroom?jurisdiction=karnataka_kmc
# Returns 404 if no specific row for that jurisdiction exists.
```

### Get one with fallback to baseline

```bash
GET /admin/standards/clearance/door_main_entry?resolve=true&jurisdiction=karnataka_kmc
# Returns the india_nbc row if Karnataka has no override.
# Response includes `jurisdiction: "india_nbc"` so the caller knows
# it's the baseline.
```

### View history

```bash
GET /admin/standards/clearance/door_interior/history
```

### Update a rule

```bash
POST /admin/standards/clearance/door_interior \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "width_mm": [820, 920],
      "height_mm": [2050, 2150]
    },
    "notes": "Updated to align with accessibility upgrade",
    "source_section": "NBC 2016 Part 4 §3.2.1 (revised May 2026)",
    "reason": "WG-2 review outcome"
  }'
```

Behind the scenes: existing row → `is_current=False`, new row at
`version=2`, full before/after diff in `audit_events`.

---

## Programmatic access

```python
from app.services.standards import (
    resolve_standard,
    list_standards_by_category,
    check_door_width,
    check_corridor_width,
    check_room_area,
)

# Direct lookup
door = await resolve_standard(
    session,
    slug="door_main_entry",
    category="clearance",
    jurisdiction="india_nbc",
)
# door["data"]["width_mm"] == [1000, 1200]

# Validator helpers — return same shape as legacy `check_door` etc.
result = await check_door_width(
    session,
    door_type="main_entry",
    width_mm=950,
    jurisdiction="india_nbc",
)
# result == {
#   "status": "warn_low",
#   "message": "main_entry door width 950mm below 1000mm.",
#   "reference": "Main Entry Door",
#   "source_section": "BRD Layer 1B — clearance & egress",
#   "jurisdiction_used": "india_nbc",
# }

# Bulk read for prompt injection
all_clearances = await list_standards_by_category(
    session, category="clearance", jurisdiction="maharashtra_dcr"
)
# Returns Maharashtra rows where present, baseline elsewhere.
# (use list_active for strict filtering instead.)
```

Stage 4 will wrap these as agent tools (`lookup_standard`,
`check_clearance`, `check_room_size`) — same pattern as Stage 2's
`estimate_project_cost`.

---

## Stage 3C — MEP rows

Stage 3C added **~90 MEP rows** to the same table — `category='mep'`,
with four subcategories.

### Subcategory map

| Subcategory | What it holds | Sample slugs |
|---|---|---|
| `hvac` | Air changes / hr, CFM/person, cooling load, duct velocities, equipment bands, duct sizing tables, register ratings | `mep_hvac_ach_bedroom`, `mep_hvac_equipment_bands`, `mep_hvac_duct_round_diameter_table` |
| `electrical` | Lux levels, circuit loads, power density, fixture catalogue, outlet catalogue, outlet count rules, task-lighting recipes, layout rules | `mep_elec_lux_office_general`, `mep_elec_fixture_led_downlight_18w`, `mep_elec_outlet_rule_kitchen` |
| `plumbing` | DFU, WSFU, pipe sizing tables, slope rules, vent stack tables, trap sizes, water demand | `mep_plumb_dfu_water_closet`, `mep_plumb_pipe_by_dfu_table`, `mep_plumb_hunters_curve_flush_tank` |
| `system_cost` | Per-m² INR cost bands for major MEP systems | `mep_system_cost_hvac_split_residential`, `mep_system_cost_electrical_commercial` |

### Row patterns

**Scalar lookup** (per-room / per-fixture / per-use):
```json
{
  "slug": "mep_hvac_ach_bedroom",
  "category": "mep",
  "subcategory": "hvac",
  "data": { "room_type": "bedroom", "air_changes_per_hour": 2.0 }
}
```

**Catalogue entry** (single fixture / outlet):
```json
{
  "slug": "mep_elec_fixture_led_downlight_18w",
  "data": {
    "fixture_key": "led_downlight_18w",
    "lumens": 1700, "watts": 18,
    "mount": "recessed_ceiling", "beam": "wide", "use": "ambient"
  }
}
```

**Lookup table** (entire band collapsed into one row):
```json
{
  "slug": "mep_hvac_equipment_bands",
  "data": {
    "entries": [
      {"capacity_tr": 0.8, "label": "0.75 TR wall split"},
      {"capacity_tr": 1.2, "label": "1.0 TR wall split"},
      … 8 more …
    ]
  }
}
```

**Task-lighting recipe** (multi-zone room):
```json
{
  "slug": "mep_elec_task_lighting_kitchen",
  "data": {
    "room_type": "kitchen",
    "zones": [
      {"zone": "counter_run", "fixture_key": "led_undercabinet_8w",
       "target_lumens": 500, "count_default": 3},
      {"zone": "island_pendants", "fixture_key": "led_pendant_20w",
       "target_lumens": 800, "count_default": 2}
    ]
  }
}
```

### MEP sizing helpers (DB-backed)

`app/services/standards/mep_sizing.py` mirrors every legacy helper in
`app.knowledge.mep` — same return shape, but reads from DB:

```python
from app.services.standards import mep_sizing

# HVAC
await mep_sizing.hvac_cfm(session, room_volume_m3=80, use_type="bedroom")
await mep_sizing.cooling_tr(session, area_m2=120, use_type="office_general")
await mep_sizing.equipment_shortlist(session, tonnage_required=1.3)
await mep_sizing.duct_round_diameter(session, cfm=350)

# Electrical
await mep_sizing.lighting_circuits(session, area_m2=100, use="residential")
await mep_sizing.ambient_fixture_count(
    session, area_m2=20, lux_target=300,
    fixture_key="led_downlight_18w",
)
await mep_sizing.outlet_estimate(session, room_type="kitchen", perimeter_m=12.0)

# Plumbing
await mep_sizing.pipe_size_for_dfu(session, total_dfu=20)
await mep_sizing.water_supply_demand_gpm(session, total_wsfu=15)
await mep_sizing.supply_pipe_size_for_gpm(session, gpm=20)
await mep_sizing.vent_size_for_dfu(session, total_dfu=15, developed_length_m=20)
await mep_sizing.fixture_water_supply_summary(
    session,
    fixtures=["water_closet", "wash_basin", "shower", "kitchen_sink"],
)

# System cost
await mep_sizing.system_cost_estimate(
    session, system_key="hvac_split_residential", area_m2=100,
)

# Pure physics — sync, no DB read
mep_sizing.equipment_capacity(tonnage=2.0)
# → {"tonnage": 2.0, "btu_per_hr": 24000, "kw_thermal": 7.034}
```

Stage 4 will wrap these as agent tools (`size_hvac`, `size_lighting`,
`size_plumbing`, `mep_system_cost`).

### Jurisdiction overrides for MEP

Same pattern as Stage 3B. Want stricter Maharashtra DCR ventilation
for bedrooms?

```sql
INSERT INTO building_standards (
  id, slug, category, jurisdiction, subcategory, display_name, data,
  source_section, source_doc, version, is_current, effective_from, source
) VALUES (
  md5(random()::text),
  'mep_hvac_ach_bedroom', 'mep', 'maharashtra_dcr', 'hvac',
  'HVAC — Air changes per hour, bedroom (Maharashtra DCR)',
  '{"room_type": "bedroom", "air_changes_per_hour": 2.5}',
  'Maharashtra DCR 2034 §X', 'Maharashtra-DCR-2034',
  1, TRUE, NOW(), 'admin:override'
);
```

Resolver picks the MH override for Mumbai projects, falls back to BRD
for the rest.

---

## Stage 3D — Manufacturing rows

Stage 3D added **~45 manufacturing rows** to the same table —
`category='manufacturing'`, with seven subcategories.

### Subcategory map

| Subcategory | What it holds | Sample slugs |
|---|---|---|
| `tolerance` | ±mm bands per dimension category | `mfg_tolerance_structural`, `mfg_tolerance_cosmetic`, `mfg_tolerance_material_thickness` |
| `joinery` | Wood joinery options with strength/difficulty/use | `mfg_joinery_mortise_tenon`, `mfg_joinery_dovetail`, `mfg_joinery_pocket_hole` |
| `welding` | Welding methods + applications | `mfg_welding_GMAW_MIG`, `mfg_welding_GTAW_TIG`, `mfg_welding_brazing` |
| `lead_time` | Manufacturing weeks ranges per discipline | `mfg_lead_time_woodworking_furniture`, `mfg_lead_time_metal_fabrication` |
| `moq` | Minimum-order-quantities | `mfg_moq_woodworking_small_batch`, `mfg_moq_cast_hardware` |
| `qa_gate` | The 5 BRD canonical QC stages | `mfg_qa_gate_material_inspection`, `mfg_qa_gate_dimension_verification`, … |
| `process_spec` | Whole-discipline rollup specs + `precision_requirements` + `bending_rule` | `mfg_process_spec_woodworking`, `mfg_process_spec_metal_fabrication`, `mfg_precision_requirements` |

### Manufacturing lookup helpers

`app/services/standards/manufacturing_lookup.py` mirrors every legacy
helper plus adds new accessors:

```python
from app.services.standards import manufacturing_lookup as ml

# Tolerances
await ml.tolerance_for(session, "structural")          # → 1.0 (mm)
await ml.tolerance_for(session, "cosmetic")            # → 2.0
await ml.tolerance_for(session, "material_thickness")  # → 0.5
await ml.tolerance_for(session, "hardware_placement")  # → 5.0

# Lead times + MOQ
await ml.lead_time_for(session, "woodworking_furniture")  # → (4, 8) weeks
await ml.moq_for(session, "cast_hardware")                # → 50

# Joinery + welding
await ml.joinery_lookup(session, "mortise_tenon")
# → {"strength": "very high", "difficulty": "high", ...}
await ml.welding_lookup(session, "GMAW_MIG")

# QA gates — returned in BRD canonical order
gates = await ml.list_qa_gates(session)
# [material_inspection, dimension_verification, finish_inspection,
#  assembly_check, safety_testing]

# Process specs
ws = await ml.process_spec(session, "woodworking")
# → {"joinery_core": [...], "tolerance_standard_mm": 2.0,
#    "lead_time_weeks": [4, 8], "moq_pieces": 1}

pr = await ml.precision_requirements(session)
# → {"structural_mm": 1.0, "cosmetic_mm": 2.0,
#    "material_thickness_mm": 0.5, "hardware_placement_mm": 5.0}
```

### Special note: process_spec rollups

The `process_spec` subcategory holds 7 rows that are *summary
documents* rather than single rule lookups:

| Slug | What it summarises |
|---|---|
| `mfg_precision_requirements` | BRD §3A universal tolerance dict |
| `mfg_process_spec_woodworking` | BRD §1C woodworking discipline |
| `mfg_process_spec_metal_fabrication` | BRD §1C metal fab discipline |
| `mfg_process_spec_upholstery_assembly` | BRD §1C upholstery assembly |
| `mfg_process_spec_upholstery_detail` | Operating-floor companion to upholstery assembly |
| `mfg_quality_gates_brd_spec` | Canonical QA-gate stage order (drives `list_qa_gates` sorting) |
| `mfg_bending_rule` | Metal min-radius rule (`R_min ≥ 2.5×t`) |

These act as *prompt slot fillers* — the LLM cost engine and spec
authors inject them verbatim when grounding their output.

---

## Stage 3E — Codes + structural + climate + ergonomics

Stage 3E added **~80 rows** spanning regulatory codes, structural
references, climate-zone design rules, and furniture ergonomics. Most
land in `category='code'`; furniture ergonomics tucks into
`category='space'` with `subcategory='furniture_ergonomics'`.

### Subcategory map (Stage 3E)

| Category | Subcategory | Source legacy file | Sample slugs |
|---|---|---|---|
| `code` | `nbc` | `codes.NBC_INDIA` | `code_nbc_minimum_room_dimensions`, `code_nbc_fire_egress` |
| `code` | `ecbc` | `codes.ECBC` | `code_ecbc_envelope_targets` |
| `code` | `accessibility` | `codes.ACCESSIBILITY`, `ibc.ACCESSIBILITY` | `code_accessibility_india_general`, `code_ibc_accessibility` |
| `code` | `fire_safety` | `codes.FIRE_SAFETY` | `code_fire_safety_india_general` |
| `code` | `ibc_occupancy` | `ibc.OCCUPANCY_GROUPS` | `code_ibc_occupancy_R`, `code_ibc_occupancy_B` |
| `code` | `ibc_construction` | `ibc.CONSTRUCTION_TYPES` | `code_ibc_construction_i_a`, `code_ibc_construction_v_b` |
| `code` | `ibc_egress` | `ibc.EGRESS` | `code_ibc_egress` |
| `code` | `ibc_environment` | `ibc.INTERIOR_ENVIRONMENT` | `code_ibc_interior_environment` |
| `code` | `iecc` | `ibc.ENERGY_ENVELOPE_U_VALUES_W_M2K` | `code_iecc_envelope_climate_zone_2_hot` |
| `code` | `structural` | `structural.*` + `ibc.LIVE_LOADS_KN_PER_M2` | `code_structural_live_loads_is875`, `code_structural_seismic_zones_is1893` |
| `code` | `climate` | `climate.ZONES` | `code_climate_hot_dry`, `code_climate_warm_humid` |
| `space` | `furniture_ergonomics` | `ergonomics.{CHAIRS,TABLES,BEDS,STORAGE}` | `ergonomics_chair_dining_chair`, `ergonomics_storage_wardrobe` |

### Jurisdictions

- **`india_nbc`** — NBC India + ECBC + Indian accessibility + Indian
  fire safety + IS-aligned structural + 5 NBC India climate zones +
  ergonomics (BRD §1C is India-anchored).
- **`international_ibc`** — IBC 2021 + IECC envelope U-values + ASCE 7
  live loads. Used when the project's regulatory context is non-India.

### Codes lookup helpers

`app/services/standards/codes_lookup.py`:

```python
from app.services.standards import codes_lookup as cl

# NBC compliance check (drop-in async equivalent of
# app.knowledge.codes.check_room_against_nbc)
issues = await cl.check_room_against_nbc(
    session,
    room_type="bedroom",
    area_m2=8.0,
    short_side_m=2.2,
    height_m=2.6,
)
# → [{"code": "NBC Part 3", "issue": "Area 8.0m^2 < habitable min 9.5"}, ...]

# Energy targets
ecbc = await cl.get_ecbc_targets(session)
iecc = await cl.get_iecc_envelope(session, "climate_zone_2_hot")

# IBC occupancy + egress
groups = await cl.list_ibc_occupancy_groups(session)
egress = await cl.get_ibc_egress(session)

# Structural
spans = await cl.get_span_limits(session)
result = await cl.check_span(session, material="rcc_beam", span_m=12.0)
# → {"status": "warn_high", "message": "Span 12.0m exceeds rcc_beam max 10.0m..."}

# Climate zone (alias-tolerant)
zone = await cl.get_climate_zone(session, "hot dry")  # or "Hot-Dry", "HOT_DRY"
```

### Ergonomics lookup helpers

`app/services/standards/ergonomics_lookup.py`:

```python
from app.services.standards import ergonomics_lookup as el

# Get full envelope
spec = await el.get_ergonomics(session, item_group="chair", item="dining_chair")
# → {"item_group": "chair", "seat_height_mm": [400, 450], ...}

# Range check (drop-in async equivalent of
# app.knowledge.ergonomics.check_range)
result = await el.check_range(
    session,
    category="chair",
    item="dining_chair",
    dim="seat_height",
    value_mm=350,
)
# → {"status": "warn_low", "message": "dining_chair.seat_height=350mm below min 400mm."}

# Bed under-storage band (BRD: 30–40 cm)
band = await el.bed_under_storage_band(session)
# → (300, 400)
```

---

## Migration runbook

```bash
# Fresh DB — applies all migrations 0001–0012
alembic upgrade head

# Already on Stage 3D
alembic upgrade head    # applies 0011 (codes seed) + 0012 (ergonomics seed)

# Verify row counts
curl /admin/standards?category=clearance       # ~30 rows
curl /admin/standards?category=space           # ~40 rows (rooms + furniture ergonomics)
curl /admin/standards?category=mep             # ~150 rows
curl /admin/standards?category=manufacturing   # ~45 rows
curl /admin/standards?category=code            # ~80 rows
curl /admin/standards?category=code\&jurisdiction=india_nbc       # ~55 rows
curl /admin/standards?category=code\&jurisdiction=international_ibc # ~25 rows
```

---

## What's still hardcoded after Stage 3E

| Knowledge file | Status | Migrates in… |
|---|---|---|
| `themes.py` | ❌ DB-backed (Stage 3A) | ✅ Done |
| `clearances.py` | ❌ DB-backed (Stage 3B) | ✅ Done |
| `space_standards.py` | ❌ DB-backed (Stage 3B) | ✅ Done |
| `mep.py` | ❌ DB-backed (Stage 3C) | ✅ Done |
| `manufacturing.py` | ❌ DB-backed (Stage 3D) | ✅ Done |
| `codes.py`, `ibc.py`, `structural.py`, `climate.py` | ❌ DB-backed (Stage 3E) | ✅ Done |
| `ergonomics.py` | ❌ DB-backed (Stage 3E) | ✅ Done |
| `materials.py` (physical props — density, MOR, MOE, finishes) | ✅ Stays in code | n/a — physics constants |
| `costing.py`, `regional_materials.py` | ❌ DB-backed (Stage 1, separate `material_prices` / `cost_factors` tables) | ✅ Done |
| `variations.py`, `summary.py` | ✅ Stay in code | Pure logic / prompt builders, not data |
| Frontend suggestion chips | ✅ Still hardcoded | Stage 3F |

---

## Gotchas for future-you

- **Adding a new clearance type?** Add a row via migration with the
  next-numbered Alembic file — don't update `clearances.py` directly,
  it's deprecated. Re-run seed builder tests to confirm extraction.
- **Updating an MEP sizing chart?** Use the admin endpoint or insert a
  new row via migration. The legacy `mep.py` is **read-only seed**; do
  not edit constants there.
- **Adding a new jurisdiction?** Just insert rows with the new
  `jurisdiction` value. No schema change needed. The resolver
  automatically picks them up.
- **Naming subcategories?** Stick to the table in `models/standards.py`
  docstring — adding ad-hoc subcategories breaks the agent's
  filter UI later.
- **Citing sources?** Always set `source_section` and `source_doc` on
  admin updates. Stage 11 transparency depends on these for citation
  output. MEP rows already cite ASHRAE / IPC / NBC / IS clauses where
  available.
- **Past compliance checks?** They captured the jurisdiction they used
  in their decision log. Old reports reproduce identically even if
  the rule was updated — versioning + jurisdiction tagging make this
  automatic.
