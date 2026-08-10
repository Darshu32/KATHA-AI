# Issue: Views & Diagrams generation is broken / inconsistent for real (multi-room) designs

**Owner:** _(senior dev)_ · **Reporter:** product · **Area:** backend drawing services + `/design` Views panel
**Severity:** High — the drawings the panel produces do not faithfully depict the design the user generated.
**Scope of this doc:** the "Working Drawings" (Plan / Elevation / Section / Isometric / Detail) and "Concept Diagrams" tabs in the design workspace. This is a diagnosis + fix plan, empirically verified on a real 3-room design.

---

## TL;DR

The Views panel offers **5 working drawings** and **8 concept diagrams**. Only **Plan View** renders the whole design correctly today (it was fixed this week). The other four working drawings — **Elevation, Section, Isometric, Detail** — silently **collapse to the first room only** (`spaces[0]`), so for any home with more than one room they draw one room's box and scatter the other rooms' furniture outside it. Separately, there are **three different, non-shared drawing renderers** in the codebase that disagree on style, coordinates, and completeness; the interactive panel is wired to the *weakest* of the three, while the *strongest* (geometry-true, cuts real walls with door openings) is only reachable as a file download and is completely unannotated (no room names, no dimensions, no furniture). The 8 concept diagrams are in good shape (deterministic, they render and vary with the design).

**The core fix is to converge on one renderer that iterates every room, not `spaces[0]`.**

---

## 1. Background — what the panel shows and how a design is represented

The design workspace (`frontend/components/workspace/image-workspace-mvp2.tsx`) has a **Views** panel with two groups:

- **Working Drawings** (catalogue at `image-workspace-mvp2.tsx:99`): `plan_view`, `elevation_view`, `section_view`, `isometric_view`, `detail_sheet`.
- **Concept Diagrams** (catalogue at `image-workspace-mvp2.tsx:116`): `concept_transparency`, `form_development`, `massing`, `volumetric`, `design_process`, `solid_void`, `spatial_organism`, `hierarchy`.

A design is a **DesignGraph** (JSON) with two coordinate conventions the drawings must respect:

- `spaces[]` — rooms. **Corner-origin**: `position {x, z}` is the room's near corner; `dimensions {length, width, height}` extends from there. A multi-room home has 2..N entries here.
- `objects[]` — furniture/fixtures. **Center-origin**: `position {x, z}` is the object's centre in the *same world metres* as the rooms; `dimensions {width, length, height}`.

So a correct drawing must (a) walk **every** entry in `spaces[]`, and (b) place each object into whichever room contains its centre. Any renderer that reads only `spaces[0]` is wrong by construction for real homes.

---

## 2. Wiring — how each view is generated (three parallel renderers)

| Panel button | Frontend call | Backend endpoint | Generator (file) | Renderer # |
|---|---|---|---|---|
| **Plan View** | `designApi.getFloorPlan` | `GET /projects/{id}/drawings/floor-plan` | `project_drawing_service.render_multiroom_plan_svg` | **#1** |
| **Elevation** | `getDrawingView("elevation-view")` | `GET …/drawings/elevation-view` (`drawings.py:199`) | `architectural_views_service.generate_elevation_package` (`:290`) | **#2** |
| **Section** | `getDrawingView("section-view")` | `…/drawings/section-view` (`drawings.py:215`) | `architectural_views_service.generate_section_package` (`:150`) | **#2** |
| **Isometric** | `getDrawingView("isometric-view")` | `…/drawings/isometric-view` (`drawings.py:231`) | `architectural_views_service.generate_isometric_package` (`:421`) | **#2** |
| **Detail** | `getDrawingView("detail-sheet")` | `…/drawings/detail-sheet` (`drawings.py:247`) | `architectural_views_service.generate_detail_package` (`:489`) | **#2** |
| _(download only)_ GA sheet | `…/drawings/sheet?format=` (`api-client.ts:977`) | `…/drawings/sheet` (`drawings.py:288`) | `spatial/drawings2d.{plan,section,elevation}_svg` | **#3** |
| _(dark — no UI)_ | — | `…/drawings/geometry/{view}` (`drawings.py:321`) | `spatial/drawings2d` | **#3** |
| **8 Concept Diagrams** | `designApi.generateDiagrams` | `POST /projects/{id}/diagrams` (`generation.py`) | `app/services/diagrams` (`generate_one`) + optional LLM authoring | **#4** |

**There are three different renderers for the same geometry:**

- **Renderer #1 — `project_drawing_service.render_multiroom_plan_svg`.** Schematic, all rooms + furniture, labeled. Powers Plan View. **Fixed this week** (previously it too collapsed to the primary space).
- **Renderer #2 — `architectural_views_service`.** Styled, labeled, dimensioned. Powers Elevation / Section / Isometric / Detail. **Reads `spaces[0]` only** (`_primary_space`, `architectural_views_service.py:58`). This is the bug.
- **Renderer #3 — `spatial/drawings2d` (the geometry kernel).** Projects the *real 3D Manifold solids* — true walls with door openings, all rooms. But emits **no room labels, no dimensions, no furniture, no title block**. Only reachable as the `/drawings/sheet` download; the per-view `/geometry/{view}` route is not wired to any button.

> Note also two stale/misleading strings to clean up while you're in here: the frontend comment at `image-workspace-mvp2.tsx:2774` calls the working-drawing routes "LLM-backed" — they are **deterministic** geometry functions, no model involved. And the Elevation/Section catalogue copy is written for **furniture** ("leg-base proportions", "seat depth, leg taper details" — `:101`–`:102`) even though the same buttons serve interior/architecture scopes.

---

## 3. Empirical evidence

Test design: a 3-room apartment — **LDK 6.0×4.5 m** + **Bedroom 3.6×3.2 m** + **Bathroom 3.6×1.3 m**, one piece of furniture in each (sofa / bed / WC). Each generator was called directly on that graph (repro in §5). "rooms shown" = distinct room envelopes actually drawn; "furniture" = objects drawn.

| View | Generator | Rooms shown | Furniture | Verdict |
|---|---|---|---|---|
| Plan | `render_multiroom_plan_svg` | **all 3** ✅ | all 3, each inside its room ✅ | **Correct** |
| Section | `generate_section_package` | **only LDK** | 1 stray (the bedroom's bed drawn against the LDK cut) | ❌ Collapsed |
| Elevation | `generate_elevation_package` | only LDK | none | ❌ Collapsed |
| Isometric | `generate_isometric_package` | only LDK box | all 3 objects **floating outside** the single box | ❌ Collapsed + furniture floats |
| Detail | `generate_detail_package` | only LDK | none | ❌ Collapsed |
| geometry/plan | kernel `plan_svg` | all walls (true, w/ openings) | none | 🟡 Geometry-true but **zero annotation** |
| geometry/section | kernel `section_svg` | all walls (true) | none | 🟡 Geometry-true but zero annotation |
| geometry/elevation | kernel `elevation_svg` | all walls (true) | none | 🟡 Geometry-true but zero annotation |
| 8 concept diagrams | `generate_one` | n/a (abstract) | n/a | ✅ All 8 render, no errors, output varies with the design |

**What the user sees:** open a 3BHK, click **Section** → a single living-room cut with a stray bed sitting in mid-air; click **Isometric** → one room's box with the bedroom and bathroom furniture floating off to the side. Every non-plan working drawing looks broken, and they all look broken the *same* way, because they share the same `spaces[0]` assumption.

---

## 4. Root causes

1. **Single-room collapse (the headline bug).** `architectural_views_service._primary_space()` (`:58`) returns `spaces[0]`; `_room()` (`:66`) reads only that room's `length/width/height`. Every package — `generate_section_package` / `generate_elevation_package` / `generate_isometric_package` / `generate_detail_package` — draws that one envelope. Meanwhile `_objects()` (`:74`) returns **all** objects globally, so furniture from rooms 2..N is rendered against room 1's frame and lands outside it (the "stray bed", the floating iso furniture). This is the *exact* bug Plan View had before renderer #1 was rewritten to walk all placed spaces — the fix never propagated to the other four views.

2. **Three renderers, no shared core.** Plan is fixed in `project_drawing_service`; Section/Elevation/Iso/Detail live in `architectural_views_service`; the geometry-true set lives in `spatial/drawings2d`. They diverge in style, coordinate handling, and completeness. Fixing one does nothing for the others — which is why Plan looks right and its four siblings don't.

3. **The best renderer is unannotated and mostly dark.** The kernel (`spatial/drawings2d`) already cuts real walls with openings for every room — it's the geometrically correct one — but it draws no room names, no dimension strings, no furniture, and no title block, and the per-view route (`/drawings/geometry/{view}`) isn't wired to any UI. So the strongest geometry is the least usable drawing and is only reachable as a file download.

4. **Cosmetic/trust issues.** Furniture-worded catalogue copy for room-scale views (`:101`–`:102`); the stale "LLM-backed" comment (`:2774`).

---

## 5. Reproduction

**In the app:** generate any multi-room home (e.g. "3BHK apartment, 1100 sqft, modern") → open the **Views** panel → click Section / Elevation / Isometric / Detail. Compare against Plan View (correct).

**Headless (isolates the generators, no auth/DB):** run this from `backend/` with `PYTHONPATH=$PWD .venv/bin/python`:

```python
from app.services import architectural_views_service as A
from app.services.project_drawing_service import render_multiroom_plan_svg
GRAPH = {  # 3 rooms, corner-origin; 3 objects, center-origin
  "design_type":"interior","theme":"modern",
  "spaces":[
    {"id":"ldk","name":"Living Dining Kitchen","room_type":"living_dining_kitchen","position":{"x":0,"z":0},"dimensions":{"length":6.0,"width":4.5,"height":2.9}},
    {"id":"bed1","name":"Bedroom","room_type":"bedroom","position":{"x":6.0,"z":0},"dimensions":{"length":3.6,"width":3.2,"height":2.9}},
    {"id":"bath1","name":"Bathroom","room_type":"bathroom","position":{"x":6.0,"z":3.2},"dimensions":{"length":3.6,"width":1.3,"height":2.9}}],
  "objects":[
    {"id":"sofa","name":"Sofa","type":"sofa","role":"furniture","position":{"x":1.6,"z":3.6},"dimensions":{"width":2.2,"length":0.9,"height":0.8}},
    {"id":"bed","name":"Bed","type":"bed","role":"furniture","position":{"x":7.8,"z":1.6},"dimensions":{"width":1.6,"length":2.0,"height":0.6}},
    {"id":"wc","name":"WC","type":"toilet","role":"fixture","position":{"x":7.8,"z":3.8},"dimensions":{"width":0.5,"length":0.7,"height":0.8}}]}
open("plan.svg","w").write(render_multiroom_plan_svg(GRAPH))            # all 3 rooms ✅
open("section.svg","w").write(A.generate_section_package(GRAPH)["svg"]) # only LDK ❌
```

`plan.svg` shows all three rooms + furniture; `section.svg` shows only the LDK envelope with the bedroom's bed floating in it.

---

## 6. Recommended fix & priority

**P0 — stop the collapse (small, unblocks the prototype).** In `architectural_views_service`, replace the `_primary_space` / `_room` single-room assumption with a whole-building pass: compute the union bbox over **all** `spaces[]`, draw **every** room envelope, and assign each object to the room whose footprint contains its centre (the same containment logic renderer #1 already uses). This turns Section/Elevation/Iso/Detail into honest multi-room drawings. Section/Elevation should cut/project along a chosen axis across all rooms; Isometric should draw each room's box.

**P1 — converge on one renderer (the real fix).** Three renderers for one geometry is the root disease. Promote the **kernel (`spatial/drawings2d`)** to the single source of truth for all orthographic views and **add an annotation layer** on top of it: room labels from `spaces[].name`, dimension strings from each room's bbox, furniture projection from `objects[]`, and a title block. Then wire the panel's five buttons (and the GA sheet download) to that one path and delete renderers #1 and #2. Result: one geometry, consistently projected to plan / section / elevation / iso / detail, all annotated, all multi-room.

**P2 — polish.** Rewrite the Elevation/Section catalogue copy for building/interior scope (drop "leg taper" etc.); fix the stale "LLM-backed" comment; optionally expose `/drawings/geometry/{view}` so the geometry-true single views are viewable, not just downloadable.

**Concept diagrams:** no action needed for the prototype — all 8 render and respond to the design. (One future note: the richer LLM-authored variant exists behind an `authored=true` flag the frontend never sends, so users only ever see the deterministic base. Fine for now.)

---

## Appendix — file/line index

- Frontend panel + catalogues: `frontend/components/workspace/image-workspace-mvp2.tsx` — working drawings `:99`, concept diagrams `:116`, view dispatch `open()` `:2777`, stale "LLM-backed" comment `:2774`, `DRAWING_SLUG` `:2767`.
- Working-drawing routes: `backend/app/routes/drawings.py` — elevation `:199`, section `:215`, isometric `:231`, detail `:247`, GA sheet `:288`, geometry/{view} `:321`; `PIECE_SCOPES` `:45`, `_GEO_VIEWS` `:42`.
- **Buggy renderer #2:** `backend/app/services/architectural_views_service.py` — `_primary_space` `:58`, `_room` `:66`, `_objects` `:74`, section `:150`, elevation `:290`, isometric `:421`, detail `:489`.
- Fixed renderer #1 (plan): `backend/app/services/project_drawing_service.py` — `render_multiroom_plan_svg`.
- Geometry-true renderer #3: `backend/app/services/spatial/drawings2d.py` — `plan_svg` `:257`, `section_svg` `:249`, `elevation_svg` `:253`.
- Concept diagrams: `backend/app/routes/generation.py` — `_AUTHORED_DIAGRAMS` `:105`, deterministic base via `app/services/diagrams.generate_one`.
