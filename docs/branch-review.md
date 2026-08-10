# Branch: `feat/multiroom-drawings-massing`

**12 commits · 22 files · +2,471 / −288 · 789 backend tests passing · 0 TypeScript errors.**

**In one line:** fixes the broken architectural drawings, extends the geometry so real
facades (recesses, screens) can exist, and adds the **design-partner layer** the founding
spec was missing — the system now reasons from constraints (climate, program) to design
moves, across both exterior and interior.

---

## Review

### A · Fixed the broken drawings & geometry (P0)
- `cc690ad` — multi-room working drawings via a shared geometry core (`spatial/graph_geometry.py`).
  Plan / Section / Elevation / Isometric / Detail now draw **every** room instead of collapsing
  to room 1; also fixes an object width/length transposition.
- `99806c3` — diagnosis write-up for the collapse (`docs/issue-views-and-diagrams.md`).
- `1ade879`, `3ca38e3` — earlier fixes: multi-room plan preview + furniture in its own room.

### B · Extended the geometry so real facades exist
- `fa86909` — recessed loggias (void-carving) + timber brise-soleil **screens** (real slat arrays).
- `5555e79` — deterministic material colours (brick→cream, timber→dark) + auto screen gradient.
  No img2img, no Replicate.

### C · The design-partner layer (constraint → reasoning)
- `1fc4e1c` — `design_reasoning.py`: climate becomes a **driver** (brise-soleil, orientation,
  glazing) with rationale.
- `b3ce51c` — wired climate reasoning into the generation front door (`site` brief → design + rationale).
- `11f889d` — deepened: central **courtyard** + envelope moves; they compose.
- `bb305d7` — `program_reasoning.py`: "3BHK" → NBC-grounded room program → placed plan.
- `8294bb5` — wired program into the pipeline (hybrid: grounded core + kept model-detected specials).
- `73302c0` — scope-neutral rationale label (climate + program).

**Three reusable cores added** — all pure, deterministic, unit-tested:
`spatial/graph_geometry.py` (drawing geometry) · `design_reasoning.py` (climate→form) ·
`program_reasoning.py` (brief→rooms).

| Proven | How |
|---|---|
| Backend logic | 789 unit tests |
| End-to-end generation | Live LLM runs: facade, climate→brise-soleil+courtyard, 3BHK+study→placed plan |
| Frontend types | 0 TS errors |
| **Not yet verified** | The live **UI** — see the checklist below |

---

## Click-through checklist (before merge)

> **First: restart the backend on :8000** unless it runs with `--reload` — the reasoning
> pipeline is new code. Open **localhost:3001/design**.

1. **Interior program + drawings.** Prompt: *"3BHK apartment, 1100 sqft"* → Generate.
   Expect a *"Design decisions · N applied"* toast; open **Views** → Plan/Section/Elevation/
   Isometric/Detail each show **all** rooms with dimensions.
2. **Interior special kept.** Prompt: *"3BHK with a study, 1100 sqft"*. The plan includes a **Study**.
3. **Exterior climate reasoning.** Left rail: Space&Site orientation = **West**, Regulatory
   climate = **Hot & Dry**. Prompt: *"a cream-brick house exterior"*. The toast mentions a
   **brise-soleil / courtyard**; the 3D shows shading and/or a central courtyard.
4. **Regression sanity.** Prompt: *"a modern living room"* → normal single-room generation,
   no program toast, nothing collapsed.
5. **No console errors** during the above.
