# KATHA AI — Phase 1 Gap Analysis

Codebase audit vs. Phase 1 BRD (Apr–June 2026, 8–9 weeks).

## Stack snapshot

- **Frontend:** Next.js 15, React 19, TS, Tailwind, Three.js, Framer Motion, Zustand
- **Backend:** FastAPI, SQLAlchemy (Postgres async), Celery, OpenAI SDK
- **Shared:** `packages/design-graph` (TS canonical schema)
- **Models:** User, Project, DesignGraphVersion, Design, EstimateSnapshot

---

## Layer-by-layer: Done vs. Todo

### Layer 1 — Input & Knowledge Base

**Done**
- Chat-driven brief input (chat workspace, prompt input, suggestion chips)
- Project CRUD with style/site metadata (location, climate zone)
- Theme presets in UI: Modern, Contemporary, Minimalist, Traditional, Rustic, Industrial, Scandinavian, Bohemian, Luxury, Coastal
- Architecture topic classifier (vastu, facade, materials, structural, MEP, lighting, sustainability, space-planning)
- Material/furniture/fixture/service/labor rate catalogs in `estimation/catalog.py` (INR-based)
- Quality multipliers (economy → luxury)

**Todo**
- Structured design-brief form (project type, space params, client reqs, regulatory context) — currently only free-text chat
- **BRD themes missing:** Pedestal, Mid-Century Modern (BRD-specified). Map current 10 themes to BRD's 5 + custom.
- Architecture standards DB: space planning (residential/commercial/hospitality m² rules), clearance & egress (door 900mm, corridor 800/1200mm, stair 180/280mm), structural logic (column spacing, spans by material, loads), MEP sizing rules (CFM, circuits, DFU)
- Building codes: NBC (India), IBC (global), ECBC, accessibility, fire safety — not embedded
- Product knowledge: furniture ergonomic ranges (chair 40–45cm seat, table 72–75cm, bed 90×200/140×200, storage depths), material properties (density, MOR/MOE, cost/kg, lead times), manufacturing constraints (tolerances ±1/±2/±0.5mm, joinery, lead times, MOQ)
- Regional material availability + climate-specific defaults

### Layer 2 — Design Generation Engine

**Done**
- `generation_pipeline.py` + `ai_orchestrator.py` — AI produces `DesignGraph` JSON (spaces, objects, materials, lighting)
- Version history (DesignGraphVersion), theme swap (`theme_engine.py`), local edits via prompt
- 2D floor plan canvas (SVG) + Three.js 3D scene, dimension lines, draggable objects
- Drawing-type enum covers plans, elevations, sections, MEP, HVAC, furniture, finishing, working drawings

**Todo**
- **Parametric logic:** current graph is static LLM JSON, no rule-based proportions / constraint solver. BRD requires theme → proportions/materials/colors/hardware/ergonomics pipeline.
- **Theme rule packs:** e.g., Mid-Century = walnut + tapered legs + brass + warm neutrals (as executable rules, not just style strings)
- **8 auto-diagrams** (concept transparency, form development, massing, volumetric, design process, solid-vs-void, spatial organism, hierarchy) — none exist
- Design variations (parametric swaps, style adaptations, modular extensions)
- Custom theme generator

### Layer 3 — Technical Specification

**Done**
- `drawing_engine.py` — floor plan package generator: walls (0.2m), doors (0.9×2.1m), windows (1.5×1.2m), MEP symbols (switch/socket/light/vent), line types, furniture by room type
- `/drawings/floor-plan` endpoint
- 3D scene via `render_engine.py` (Three.js schema)

**Todo**
- **Elevation + section + detail** view generators (only plan exists)
- **3D isometric / exploded assembly** views
- Material specification sheet (template auto-filled: primary structure / secondary / hardware / upholstery / finishing with supplier + lead time + cost)
- Manufacturing spec (woodworking/metal/upholstery/assembly notes with tolerances, welding, webbing, torque)
- MEP spec generator (HVAC CFM, electrical lux/circuits, plumbing DFU/trap/slope)
- Precision tagging (±1mm structural, ±2mm cosmetic, ±0.5mm thickness)

### Layer 4 — Cost Modeling & Estimation

**Done** *(strongest layer)*
- `estimation_engine.py` + submodules: calculators, pricing_control, scenarios, confidence, breakdown, catalog_handler, history, FX, validation
- Line-item breakdown (material/furniture/fixture/service/labor/misc) × quality multiplier
- Scenario generation (optimistic/pessimistic/base), confidence scoring, audit logs
- Versioned estimate snapshots, multi-currency with FX fallback

**Todo**
- Waste factor (10–15%) as explicit input, not implicit
- Labor hour estimation from complexity (currently rate × area; BRD wants hours × hourly-rate by trade)
- Overhead breakdown (workshop 30–40%, QC 5–10%, packaging 10–15%)
- Margin layers (designer 25–50%, manufacturer 30–60%, retail 40–100%, customization 10–25%)
- Sensitivity analysis (material/labor/overhead ±10% → price delta; volume curves 1/5/10 pieces)
- Cost breakdown report formatted per BRD template

### Layer 5 — Import / Export

**Done**
- DesignGraph JSON export (implicit), SSE chat streaming, estimate JSON
- Floor plan payload via API

**Todo** *(biggest gap)*
- **Export:** PDF (tech drawings + specs + cost), DWG/DXF (AutoCAD), Revit/IFC (BIM), 3DS/FBX/OBJ/GLTF, STEP/IGES, DOCX, XLSX, PPTX, HTML interactive viewer, G-code / CAM prep
- **Import:** PDF (dimension extract), images (JPG/PNG style refs), CAD (DWG/DXF/STEP), 3D (OBJ/FBX/GLTF), CSV/Excel data, site plans, design-brief docs

### Layer 6 — Knowledge Integration

**Done**
- Quality multipliers applied automatically to catalog rates
- Architecture topic classifier for chat knowledge Q&A
- Confidence scoring on estimates

**Todo**
- Auto-apply proportions/materials/colors from theme to design
- Ergonomic range checks against dimensions (flag out-of-standard)
- Building code compliance checker (fire egress, accessibility, structural)
- Manufacturing feasibility warnings (tolerance too tight, impossible joinery)
- Recommendations engine ("for mid-century use walnut…", "material cost high, alternatives…", volume-pricing nudges)
- Regional cost adjustments by location

### Layer 7 — Haptic-Ready Data

**Done**
- Structured JSON (dimensions, materials, positions, unit rates) — foundation is there
- Versioning + unit system

**Todo**
- Material haptic properties (texture ID, temp °C, friction coef, firmness)
- Interaction parameters (which dims adjustable, ranges, real-time cost triggers, material swap options)
- Feedback-loop rules encoded ("height +1cm → ₹X", "walnut→oak → –₹Y")
- Haptic export bundle (JSON/XML packaged payload)

---

## Cross-cutting gaps

- **LLM:** hardcoded OpenAI; BRD context suggests Anthropic. Abstract provider.
- **No CAD-native pipeline:** everything is JSON → SVG/Three.js. Need a real geometry kernel (e.g., OpenCascade via pythonocc, or ezdxf for DXF, ifcopenshell for IFC) for pro exports.
- **No parametric/rule engine:** LLM writes the graph; BRD wants rules that generate + validate it.
- **No structured brief capture:** only chat.

---

## Recommended execution order (8 weeks)

Per BRD timeline, adjusted for what exists:

1. **Week 1–2 — Knowledge base:** embed architectural standards, product ergonomics, material properties, manufacturing constraints, building codes. Extend `catalog.py` → full knowledge DB. Map BRD themes (start with Pedestal/Theme V).
2. **Week 3–4 — Parametric + diagrams:** rule engine over DesignGraph. 8 auto-diagrams. Variation system.
3. **Week 5–6 — Tech specs:** elevation/section/detail generators, material spec sheets, manufacturing spec, MEP spec, precision tags.
4. **Week 7–8 — Cost refinement + export + haptic prep:** waste/labor-hours/overhead/margin breakdown, sensitivity analysis. PDF/DWG/STEP/Revit/DOCX/XLSX/PPTX exporters. Import pipeline. Haptic JSON bundle.
5. **Week 9 — Polish, beta test 2–3 real projects.**

## Biggest risks

- **CAD export** (DWG/Revit/STEP) is specialist work — budget more time or use libraries (ezdxf, ifcopenshell, pythonocc).
- **Parametric engine** replaces LLM-only generation — architectural shift, plan carefully.
- **Knowledge base scope** is huge (codes + ergonomics + materials + manufacturing). Prioritize by theme V first.
