# How This Actually Works

> The technical mechanics behind an AI-native spatial architecture platform.

**Who this is for:** the developer building it, and the architect working alongside them.

This is not a list of libraries — that's a separate document (`spatial-stack-spec.md`). This explains *why* the pieces are what they are, so that when something breaks you know which layer it broke in.

**A note on the two-person split:** roughly, sections 1–3 and 6–8 are the developer's territory, sections 4–5 are where the architect's knowledge is load-bearing and can't be substituted by code. Section 5 in particular — drawing conventions — is knowledge that exists in an architect's head and essentially nowhere in a library.

## Table of contents

1. [Geometry representation](#1-geometry-representation--the-choice-that-cascades)
2. [Constraint solving](#2-constraint-solving--how-a-sketch-holds-together)
3. [What IFC actually is](#3-what-ifc-actually-is)
4. [Layout generation](#4-layout-generation--how-a-plan-gets-invented)
5. [Deriving drawings from 3D](#5-deriving-drawings-from-3d--the-hard-part)
6. [Rendering at scale](#6-rendering-100k-elements)
7. [Multiplayer on geometry](#7-why-multiplayer-on-geometry-is-hard)
8. [The spec-first architecture](#8-why-spec-first-resolves-most-of-the-above)
9. [Glossary](#9-glossary)

---

## 1. Geometry representation — the choice that cascades

Four families. This choice determines what's possible everywhere downstream.

### Mesh

Triangles. GPU-native, fast, universally supported.

The limitation: a cylinder is 64 flat quads, not a cylinder. There is no notion of "this face is planar" or "this edge is tangent to that surface." Exactness is gone the moment you tessellate. You cannot fillet a mesh meaningfully, and you cannot export it to STEP.

### B-rep (Boundary Representation)

The real CAD representation. It is a topological graph with geometry attached.

```
Vertex → Edge → Wire → Face → Shell → Solid → Compound
```

That is literally OCCT's TopoDS hierarchy. The split matters:

- **Topology** holds connectivity — which edges bound which face, which faces meet at an edge.
- **Geometry** hangs off it — a Vertex owns a 3D point, an Edge owns a curve (line, circle, B-spline) plus a parameter interval `[t₀, t₁]`, a Face owns a surface (plane, cylinder, NURBS patch) plus trimming loops defined in the surface's UV parameter space.

The face is exact. A cylindrical face knows it is a cylinder with a radius and an axis. That is what makes filleting, tangency queries, and STEP export possible.

### CSG (Constructive Solid Geometry)

An unevaluated tree of primitives and boolean operations. "Is this point inside?" is answered by descending the tree. You never hold boundaries in memory, so "select this face" is not a meaningful operation. Fine as an authoring paradigm, insufficient as a model.

### SDF / implicit

A function `f(x,y,z) → signed distance to surface`. Negative inside, positive outside.

Booleans become trivially robust — union is `min(a,b)`, subtraction is `max(a,−b)`. No intersection curves to compute, no degenerate cases. The cost: you need marching cubes or dual contouring to render anything, and sharp edges get rounded off unless you work hard.

### Why booleans are the hard part

Subtracting a window opening from a wall sounds trivial. In a B-rep kernel it requires:

1. **Surface–surface intersection** → produce the intersection curves. For two NURBS surfaces this is numerically traced, not solved analytically.
2. **Face splitting** along those curves → new trimming loops in UV space.
3. **Classification** — for each resulting face fragment, determine inside or outside the other solid.
4. **Sewing** the surviving fragments back into a closed, watertight shell.

Step 1 is where implementations fail. The pathological cases:

- **Tangential contact** — surfaces touching without crossing. Is that an intersection curve or not?
- **Coplanar faces** — two walls whose faces lie in the same plane. Classification is ambiguous.
- **Near-coincident vertices** — two points 0.0000001mm apart. Same point or not?

Every B-rep kernel carries a **tolerance per topological entity** to absorb this. The classic failure mode is **tolerance growth**: an operation widens a tolerance, the next operation inherits and widens it further, and eventually the topology is unrecoverable. This is why complex CAD models mysteriously corrupt.

Manifold's contribution is sidestepping the problem entirely: it operates on triangle meshes, uses exact arithmetic predicates for classification, and guarantees manifold (watertight, non-self-intersecting) output by construction. That is where the ~1000× speedup over older CSG libraries comes from. The trade: you are in mesh land, with no exact surfaces.

### The topological naming problem

This is the deepest issue in parametric CAD, and it hits an AI-driven system harder than a human-driven one. It is worth understanding before it bites.

You apply a fillet to "Edge 7." Then a parameter changes — a room gets wider. The model rebuilds. The new topology has a different edge count, and Edge 7 is now Edge 9, or has ceased to exist. Your fillet now references garbage, and the rebuild fails.

This is why FreeCAD models shatter when you change a parameter upstream. Commercial kernels spend enormous effort on **persistent naming** — identifying topological entities by geometric heuristics (position, adjacency, which feature generated them) rather than by index. Every solution is partial.

**The generative escape hatch:** don't keep a feature history at all. Regenerate the entire model from the spec on every change. Nothing references anything by index, so nothing can break. This is a genuine advantage of the generate-from-spec approach over traditional parametric modeling — the hardest problem in the field simply doesn't arise.

---

## 2. Constraint solving — how a sketch holds together

A 2D sketch is a set of entities, each with free parameters:

| Entity | Parameters | DOF |
|---|---|---|
| Point | x, y | 2 |
| Line | two endpoints | 4 |
| Circle | cx, cy, r | 3 |
| Arc | cx, cy, r, θ₁, θ₂ | 5 |

Constraints are equations over those parameters:

```
Coincident(p₁, p₂):      x₁ − x₂ = 0
                         y₁ − y₂ = 0
Distance(p₁, p₂, d):     (x₁−x₂)² + (y₁−y₂)² − d² = 0
Horizontal(line):        y₁ − y₂ = 0
Parallel(l₁, l₂):        (x₂−x₁)(y₄−y₃) − (y₂−y₁)(x₄−x₃) = 0
Tangent(line, circle):   dist(center, line) − r = 0
```

Stack them all and you have a system `F(q) = 0`, where `q ∈ ℝⁿ` is every parameter in the sketch and `F: ℝⁿ → ℝᵐ` is every constraint equation.

### Reading the Jacobian

The Jacobian `J = ∂F/∂q` (the matrix of partial derivatives of every equation with respect to every parameter) tells you the health of the system:

- `DOF = n − rank(J)` — remaining degrees of freedom
- `rank(J) < m` → the constraints are **redundant or conflicting**. Two constraints saying the same thing, or contradictory things.
- `DOF > 0` → **under-constrained**. Infinitely many solutions; the solver returns the one nearest the current state.
- `DOF = 0` → **fully constrained**. Exactly one solution. This is what an architect means by a dimensioned drawing.

Surfacing DOF in the UI is what makes a sketcher feel intelligent rather than opaque — the user sees why something moved.

### Solving

The system is nonlinear, so this is nonlinear least squares: minimize `‖F(q)‖²`.

**Newton–Raphson**

```
q ← q − J⁺ F(q)        (J⁺ = pseudo-inverse)
```

Quadratic convergence near the root. Diverges badly when the starting point is far off.

**Levenberg–Marquardt**

```
(JᵀJ + λI) δ = −Jᵀ F
q ← q + δ
```

The damping parameter λ interpolates between two behaviours: λ→0 gives Gauss–Newton (fast, fragile), λ→∞ gives gradient descent (slow, safe). λ adapts each iteration based on whether the last step improved the residual.

**DogLeg** — a trust-region method. Computes both the Gauss–Newton step and the steepest-descent step, and takes a blend of them that stays inside a trust radius. The radius grows on success and shrinks on failure. Generally the most robust of the three, and typically the default.

### Two practical facts

**The initial guess dominates everything.** These solvers behave badly from random starts and beautifully from near-solutions. Since a generative layout system already places rooms approximately correctly before the solver runs, it is always operating in the favourable regime. This is a structural advantage worth knowing about.

**Decomposition makes it interactive.** Solving 5,000 coupled equations at 60fps is not feasible. Real solvers decompose the constraint graph into rigid clusters — subsets whose internal DOF is zero — solve each independently, then position clusters relative to one another. The relevant literature is DR-planning and C-tree decomposition.

### Dragging

When a user drags a wall, the solver adds a **temporary constraint** pulling the dragged point toward the cursor. Temporary constraints do not reduce DOF and yield to real constraints when they conflict. That mechanism is why dragging in good CAD feels like manipulating a physical linkage rather than fighting a rubber band.

---

## 3. What IFC actually is

IFC is not a geometry format. It is a **schema-defined object model for buildings**. Treating it as a 3D file format is the most common and most costly misunderstanding.

The schema is written in **EXPRESS** (ISO 10303-11, the STEP modeling language). Files are usually serialized as **STEP Physical File** (ISO 10303-21) — a flat, numbered instance list:

```
#42=IFCWALLSTANDARDCASE('3vB2YO$MX4xv5uCqZZG05x',#5,'Wall-001',$,$,#101,#205,$);
#101=IFCLOCALPLACEMENT(#99,#100);
#205=IFCPRODUCTDEFINITIONSHAPE($,$,(#206));
#206=IFCEXTRUDEDAREASOLID(#207,#210,#211,3000.);
```

Parsing is easy. Understanding the model is not. The structural ideas that matter:

### Spatial hierarchy

```
IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey → elements
```

Wired together by `IfcRelAggregates` and `IfcRelContainedInSpatialStructure`. Note that containment is a **relationship object**, not a parent pointer. IFC models relationships as first-class entities throughout. This is verbose but means a relationship can carry its own properties.

### Openings are relationships, not booleans

This one surprises people:

- `IfcRelVoidsElement` links an `IfcOpeningElement` to the wall it voids
- `IfcRelFillsElement` places the door or window into that opening

The subtraction is **implied, not baked into the geometry**. It is evaluated at display time by whatever is reading the file. This is precisely why the same IFC file renders differently in different viewers — they disagree about how to evaluate the voids.

### Geometry is usually implicit

```
IfcExtrudedAreaSolid = profile + direction + depth
```

A wall is a closed 2D profile swept 3000mm upward. This is orders of magnitude smaller than a mesh and, crucially, still editable — the parameters are right there. Explicit forms exist (`IfcFacetedBrep`, `IfcTriangulatedFaceSet`) but should be a fallback, not a default.

### Placement is a chain

`IfcLocalPlacement` nests: element relative to storey, storey relative to building, building relative to site, site relative to project origin. To get world coordinates you accumulate 4×4 transformation matrices walking up the chain.

Getting this wrong is the single most common cause of "why is my model 40 kilometres from the origin."

### Property sets

`IfcPropertySet` attached via `IfcRelDefinesByProperties` carries fire rating, U-value, acoustic performance, cost codes, manufacturer data. This is the "I" in BIM — the information. A model without property sets is just a shape.

**Net:** generating valid IFC means emitting typed entities, relationship objects, implicit geometry, and placement chains. More tractable than it appears — the difficulty is schema knowledge, not code volume. The architect on the team likely already knows what a correct model looks like.

---

## 4. Layout generation — how a plan gets invented

### Classical algorithms

**Rectangular dual** — If an adjacency graph is planar and satisfies certain structural conditions (no separating triangles, properly 4-connected), it admits a rectangular dual: a partition of a rectangle into smaller rectangles whose adjacency graph is exactly the input graph. This is classical graph theory (Kozminski & Kinnen, 1985). It gives layouts that are topologically guaranteed correct — every requested adjacency is satisfied by construction.

**Slicing trees** — Recursively split the boundary horizontally or vertically; leaves are rooms. The tree encodes topology, the split ratios are free parameters. Trivially optimizable and fast. The limitation: non-slicible floorplans exist (the classic pinwheel arrangement of five rooms) and cannot be expressed this way.

**Simulated annealing** — Define an energy function — weighted sum of area error, adjacency violation, aspect ratio penalty, circulation cost, daylight access — and anneal. Slow, but fully general and still used in production systems because it accepts any objective you can write down.

**Weighted Voronoi / power diagrams** — Site weights control cell areas. Produces non-rectangular, organic plans. Useful for early massing and site strategy rather than habitable room layout.

### Learned approaches

**Graph2Plan (2020)** — retrieval-augmented generation. Encode the adjacency graph, retrieve a structurally similar plan from a database (RPLAN), then use a GNN + CNN to warp its room bounding boxes to fit the target site boundary. The retrieval step is why outputs look like plausible buildings rather than alien geometry — it inherits real design decisions.

**House-GAN++ (2021)** — relational GAN. Nodes are typed rooms, edges are required adjacencies. A message-passing GNN generates room masks; the discriminator is also relational, so it critiques the relationships, not just the pixels. Runs iteratively — generate, feed back, refine. Output is raster masks, so a vectorization stage is required.

**HouseDiffusion (2023)** — the significant one. Represents a floor plan as sets of corner coordinates and runs diffusion directly in that coordinate space. Two denoising processes run together: continuous denoising on the coordinates, and discrete denoising that snaps coordinates to an integer grid during late timesteps. Attention operates at three levels — within a room, between rooms via the adjacency graph, and globally across the plan. Output is vector geometry directly: no vectorization stage, no raster artifacts, no wobbly walls.

**FloorplanMAE (2025)** — masked autoencoder for plan completion from partial input. The relevant capability for "the architect sketched half of it, finish it."

### The pattern across all of them

> The graph is the conditioning signal. Geometry is the output.

This is the technical justification for having the language model emit **program and adjacency graph** rather than pixels or coordinates. Translating "a three-bedroom house where the kitchen opens onto the living room and the master has an ensuite" into a typed graph is a language task, which is what language models are good at. Geometry is not a language task.

---

## 5. Deriving drawings from 3D — the hard part

This is the section where the architect's knowledge is irreplaceable. Almost none of it exists in a library.

### A plan is not a top view

A floor plan is a **horizontal section**, conventionally cut at around 1200mm above finished floor level, with everything below the cut projected downward.

The construction:

1. Boolean the model against a half-space at z = 1200 → produces **cut faces**
2. Cut faces receive **poché** (solid fill or hatch) and the heaviest lineweight
3. Geometry below the cut projects as medium-weight lines
4. Geometry above the cut (beams, soffits, overhead cabinets) is drawn **dashed**

### Annotation is synthesized, not extracted

That last point matters. **Door swing arcs do not exist in the 3D model.** They are drawing convention, generated from the hinge side, the door width, and the opening angle. The same is true of:

- North arrow and scale bar
- Dimension strings and witness lines
- Room name and area tags
- Section markers and elevation flags
- Grid lines and bubbles
- Material hatches
- Level markers

A plan without these is a shape. A plan with them is a drawing. The gap between the two is where "like actual" is won or lost, and it is almost entirely convention knowledge rather than geometry.

### Sections and elevations need hidden line removal

Two families of approach:

**Exact / analytic** — OCCT's `HLRBRep_Algo`:

1. Compute **silhouette curves** — the locus of points where the surface normal is perpendicular to the view direction. For curved surfaces this is a computed curve, not an existing model edge.
2. Project every edge, including silhouettes, onto the view plane.
3. Classify each projected segment as visible or hidden by ray-casting against the full face set.
4. Output exact 2D curves.

Result is scalable, printable, editable vector geometry. Slow — this is a background job, not a per-frame operation.

**Raster** — render with a depth buffer, run edge detection on depth and normal discontinuities. Fast, gives pixels. Perfectly good for a screen preview, useless for a drawing set that will be printed at A1 and dimensioned.

### Lineweight is semantic, not geometric

The hierarchy an architect expects:

| Line type | Weight | Meaning |
|---|---|---|
| Cut edges | Heaviest | Material the section plane passes through |
| Silhouette / outline | Medium | Object boundary against background |
| Surface edges | Light | Changes in surface within an object |
| Hidden | Dashed, light | Occluded geometry shown for reference |

This classification requires knowing **what got cut** — which is semantic information from the BIM model, not something derivable from a triangle mesh. It is one of the most concrete reasons the model has to carry building semantics rather than just shape.

---

## 6. Rendering 100k+ elements

A building model is hundreds of thousands of elements. Naïve rendering — one draw call per element — will not work. Four techniques carry the load:

**Batched geometry with per-vertex element IDs** — Merge everything into a small number of large vertex buffers. Store an element ID as a vertex attribute. Selection works by rendering IDs to an offscreen buffer and reading the pixel under the cursor, rather than needing separate scene objects. This is essentially what ThatOpen's Fragments format does.

**Instancing** — Identical windows, doors, and columns collapse to one geometry plus a per-instance transform buffer. In a typical building, 60–80% of elements are instances of something. This is the single largest win available.

**BVH for picking** — A bounding volume hierarchy (three-mesh-bvh) makes raycasts O(log n) rather than testing every triangle. Without it, hover highlighting alone will drop frames.

**Storey culling** — Architects work one floor at a time. Rendering only the active storey plus context is enormous savings for almost no implementation cost.

---

## 7. Why multiplayer on geometry is hard

CRDTs converge cleanly on text because validity is **local** — inserting a character can't invalidate a paragraph elsewhere.

Geometry validity is **global**. Two users can each make an individually valid edit that is jointly invalid:

- User A widens the kitchen, user B widens the adjacent bathroom → walls now overlap
- User A deletes a door, user B moves the only other door → a room is now unreachable
- User A adds a window, user B moves the wall it sits in → orphaned opening

No general CRDT resolves this, because the conflict is **semantic** rather than positional.

### The resolution

**Apply the CRDT to the spec, not the geometry.**

The spec is a tree of typed records — rooms, walls, openings, parameters — which maps cleanly onto Yjs maps and arrays. Geometry is a deterministic pure function of the spec, so every client recomputes locally and converges automatically.

Conflicts then degrade from topology-level to scalar-level: both users edited `room.width` → last-writer-wins on a number. That is a conflict a CRDT handles natively.

Global validity is then enforced by **running validation on the merged spec and surfacing violations** to the users, rather than trying to prevent them at merge time. Architects are used to a model having open issues; they are not used to a model silently corrupting.

---

## 8. Why spec-first resolves most of the above

Worth stating plainly, because it is the through-line connecting every section:

| Problem | How spec-first addresses it |
|---|---|
| Topological naming | Full regeneration each time — nothing references entities by index |
| Solver initial guess | Generator provides a near-solution starting point |
| Multiplayer conflicts | CRDT operates on typed records, not topology |
| Versioning and diffing | Diff a JSON tree, not a mesh |
| Undo/redo | Patch history on the spec |
| Storage cost | Kilobytes instead of megabytes |
| LLM integration | Structured output is a language task; geometry is not |
| Reproducibility | Same spec, same geometry, always |

The single rule this implies: **store the spec, treat geometry as a derived artifact.** Regenerating geometry should always be cheaper and safer than storing it.

---

## 9. Glossary

For crossing the vocabulary gap between the two disciplines.

- **B-rep** — Boundary Representation. Solid geometry described by its bounding faces, edges, and vertices, with exact surface definitions.
- **BVH** — Bounding Volume Hierarchy. Spatial acceleration tree for fast ray/collision queries.
- **CRDT** — Conflict-free Replicated Data Type. Data structure that merges concurrent edits deterministically without a central server.
- **CSG** — Constructive Solid Geometry. Modeling by boolean combination of primitives.
- **DOF** — Degrees of Freedom. Number of independent parameters not pinned down by constraints.
- **EXPRESS** — The schema definition language used to specify IFC (ISO 10303-11).
- **HLR** — Hidden Line Removal. Determining which edges are visible from a viewpoint; the basis of sections and elevations.
- **IFC** — Industry Foundation Classes. Open schema-based data model for building information.
- **Jacobian** — Matrix of partial derivatives; reveals whether a constraint system is over-, under-, or fully constrained.
- **Manifold (adj.)** — A mesh that is watertight and non-self-intersecting; every edge borders exactly two faces.
- **NURBS** — Non-Uniform Rational B-Spline. Standard mathematical representation of freeform curves and surfaces in CAD.
- **OCCT** — Open CASCADE Technology. The open-source B-rep CAD kernel.
- **Poché** — The solid fill or hatch applied to material cut by a section plane. Architectural drawing convention.
- **SDF** — Signed Distance Field. Implicit surface representation as a distance function.
- **Silhouette curve** — The locus where a surface normal is perpendicular to the view direction; the visual outline of a curved object.
- **Tessellation** — Converting exact surfaces into triangles for display.
- **Tolerance** — Per-entity numerical slack in a B-rep kernel used to absorb floating-point error.
- **Topological naming** — The problem of stably identifying geometric entities across model rebuilds.
- **Trimming loop** — Curves in a surface's UV parameter space defining the boundary of the usable region of that surface.
