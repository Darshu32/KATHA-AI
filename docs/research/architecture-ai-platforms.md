# Architecture AI Platforms — Design Reference

> Captured 2026-05-19. Screenshots taken from each platform's public
> landing / product page. Use this as a reference when deciding what
> KATHA's `/design` workspace should look like.

---

## 1. Maket.ai — AI Floor Plan Studio

**URL:** https://www.maket.ai
**Tagline:** "Generate floor plans, explore layouts, and visualize your home with AI at your side."
**What it does:** Architects sketch a floor shape → AI generates room layouts → user picks a render style (Scandinavian, Mid-Century, Industrial, etc).

**Design observations:**
- **Register:** Off-white warm paper background. Soft, residential, approachable.
- **Hero:** Big black serif headline ("The AI Floor Plan Studio"). Marketing-led.
- **Product mockup:** Multi-window collage in the hero — floor-shape editor, plan canvas, render-style picker. Architects can see three workflow steps at a glance.
- **Render Style picker:** A 6×n grid of thumbnail tiles labelled with style names — matches the BRD's theme metaphor exactly.
- **Single black CTA pill** ("Get started for free"). No competing colors.
- **Cookie banner stays small + right-bottom** — doesn't blow up.

**What KATHA can borrow:**
- The thumbnail-tile theme picker layout for our theme switcher
- The multi-window product mockup style (floor + render + sidebar all visible)
- The warm-paper register feels architectural — closer to KATHA's editorial side than to LookX's neon

---

## 2. Architechtures — AI-Powered Building Design

**URL:** https://architechtures.com
**Tagline:** "AI-Powered Building Design. Generative AI building design platform."
**What it does:** Residential developer enters site constraints + program → AI generates buildable BIM solution → exports to XLSX/DXF/IFC.

**Design observations:**
- **Register:** Pure white. Black serif headline. Sober, AEC-professional.
- **Hero illustration:** Black-and-white architectural rendering of a tower — feels like a competition entry submission.
- **Three-step workflow card row** (INPUT / AI / OUTPUT) with icons + tight body copy under each.
- **Product UI screenshot** shown in a laptop bezel: tabs across top, left panel for inputs, central 3D model, right panel for live metrics ("DEVELOPMENT POTENTIAL", "BUILDING EFFICIENCY"). Dense data layout.
- **Orange CTA** ("7 Days Free Trial") — single accent.
- **Top nav:** Product · Pricing · Resources · Contact. Light, calm.

**What KATHA can borrow:**
- The **INPUT → AI → OUTPUT** three-card explainer for landing/onboarding
- The data-dense right-panel pattern with all-caps metric labels (matches BRD §4 cost breakdown reporting)
- Sober black-and-white restraint — no rainbows, no neons
- File-format badges (XLSX, DXF, IFC) shown explicitly as outputs — matches KATHA's 16-exporter brag-worthy spec

---

## 3. Veras (EvolveLAB) — Render-from-Sketch Plugin

**URL:** https://www.evolvelab.io/veras
**Tagline:** "AI-powered visualization app that plugs into your design authoring app."
**What it does:** Plugs into SketchUp / Revit / Rhino / Forma / Archicad / Vectorworks — takes a model and produces a render. Web app + native plugin.

**Design observations:**
- **Register:** **Dark.** Solid royal blue hero band, black top nav.
- **Massive sans-serif logo type** (VERAS) — branded, confident.
- **Plugin-host list** prominently rendered as text — every supported app + version. Trust signal for the AEC user.
- **Pill CTAs**: black "Try Now" + white "Buy Now" + black "Launch Web App". Three options visible at once.
- **Sub-nav at bottom**: Forum & Support · Feature Request · Manage Subscription — utility links treated as first-class.
- **Now owned by Chaos** (V-Ray maker) — banner at top.

**What KATHA can borrow:**
- The honesty of stating supported formats in the hero (KATHA could state: "Exports to PDF · DOCX · DXF · IFC · STEP · GLTF · …")
- Pill CTAs for action prioritization
- **Veras went dark** — successful precedent for an architectural-AI platform in dark register, which our user keeps gravitating toward

---

## 4. LookX.ai — AI Platform for Architects & Designers

**URL:** https://www.lookx.ai
**Tagline:** "Next generation AI platform for architects & designers. Smart · Fast · Precise."
**What it does:** Architectural visualization AI with plugins.

**Design observations:**
- **Register:** **Vivid gradient hero** — purple/pink/orange/blue blob. Heavy decorative use of color.
- **Massive white display type** in the hero.
- **Gradient CTA pill** ("Get started for free") with cyan-to-magenta fade.
- **Floating chat bubble bottom-right** (support chat).
- **Three icons + words** beneath headline: lightbulb (Smart) / rocket (Fast) / book (Precise).

**What KATHA can borrow (or reject):**
- **Reject:** the gradient maximalism. This is the opposite of architectural restraint.
- **Borrow:** the "three value props as icons under a headline" pattern is a clean way to communicate Quick / Deep / Auto modes, or "Generate / Refine / Export".
- Useful as a **counter-example** — KATHA's whole register intentionally pushes the other direction (paper, pencil-red, calm).

---

## 5. Spacely.ai — Interior Design AI

**URL:** https://www.spacely.ai
**Tagline:** "Client-Ready Renders. In Minutes."
**What it does:** Upload a room photo or sketch → AI re-styles it → split-comparison render with style prompts.

**Design observations:**
- **Register:** Clean white. Black headline + **electric blue** accent on "In Minutes."
- **Hero visual = split-screen render**: dark modern interior on the left, warm wood interior on the right — exact same camera angle.
- **Prompt overlay** at the bottom of the visual: "Style this living room in Dark Modern style, black ribbed paneling, walnut wood, charcoal grey sofa, amber pillows." — shows the *input* alongside the output.
- **"Watch Demo ▶" mini CTA** inside the visual itself.
- **Blue primary button** + black secondary button.

**What KATHA can borrow:**
- The **before/after split** visual is a great way to show "v01 vs v02" iteration
- Showing the **prompt below the render** anchors the architect to "this was the input that made that output" — useful for KATHA's edit-loop UX
- "Client-Ready Renders" framing — KATHA's exporters land here

---

## 6. Autodesk Forma — Site Design

**URL:** https://www.autodesk.com/products/forma-site-design/overview
**Tagline:** "Your go-to AI-powered cloud software for site planning and analysis."
**What it does:** Cloud-based site planning + early massing + analysis. Part of Autodesk AEC bundle.

**Design observations:**
- **Register:** **Hard dark** — pure black canvas with charcoal sidebar. Yellow active state on sidebar items.
- **Sidebar nav** (Key benefits · Features · Product bundle · Workflows · Success stories · News and updates · FAQs · System requirements) — a tall scrollable list, no icons.
- **Sidebar background:** dark charcoal, distinct from the pure-black canvas. Yellow dot + yellow text mark the active item.
- **Body text:** white, comfortable size, bulleted feature list.
- **CTA:** outlined "Explore software (video: 1:43 min.)" — confidence in the demo as the conversion path.

**What KATHA can borrow:**
- **This IS the dark-sidebar / dark-canvas register the user originally described** ("sidebar grey, context window black"). Yellow accent + charcoal-on-black hierarchy is a working precedent from the biggest name in the AEC space.
- Treating long info architecture as a **sidebar list** rather than tabs across the top — useful for the BRD §1A 5-section brief

---

## 7. TestFit — Real Estate Feasibility

**URL:** https://www.testfit.io
**Tagline:** "Automate Site Plans. Accelerate Decisions."
**What it does:** Tests buildable site plans with parking, building massing, unit mix. Used by Perkins&Will, DLR Group, Langan.

**Design observations:**
- **Register:** **Dark.** Near-black canvas, white text, **orange CTA** (single accent — same hue family as KATHA's pencil-red).
- **Hero visual = the actual product output**: a color-coded site plan with green/blue/purple unit blocks. Very technical.
- **Heavy display sans-serif** for the headline ("Automate Site Plans") — confident, almost industrial.
- **Logo strip** of enterprise customers along the bottom (Perkins&Will, DLR Group, Langan, Prologis) — heavy trust signal.
- **Search icon (magnifier)** in the top nav — power-user nav.

**What KATHA can borrow:**
- The **color-coded plan as hero visual** — show the *output*, not a marketing illustration
- The **single orange accent against dark** — close cousin to KATHA's pencil-red on dark, if you go dark
- Enterprise logo strip — once KATHA has 3+ named architects using it, this becomes valuable
- Treat the headline like a manifesto, not a sales pitch

---

## 8. Hypar — Generative Design for AEC

**URL:** https://hypar.io
**Tagline:** "Generative Design for AEC." (Logo: HYPAR)
**What it does:** Cloud generative design tool for architects. Used by HED, BSA, Flad Architects, NELSON, SLAM, Stantec.

**Design observations:**
- **Register:** **Light gray graph-paper background** with subtle architect's grid lines. Dark card centered for sign-up.
- **Brand mark:** "HYPAR" in red display type — confident, geometric, retro-architectural.
- **Right panel of sign-up card** shows a **colored 3D voxel building model** (red/green/blue/yellow blocks) — the product output as a teaser.
- **Trust strip:** "Trusted by" with grayscale logos.
- **Red CTA pill** ("Create an account for free") — same red as the logo, single accent.

**What KATHA can borrow:**
- The **graph-paper background** is *exactly* the architectural drafting metaphor KATHA already gestures toward with its register. Worth considering for the empty-state hero on `/design`.
- The 3D voxel building model as a teaser in the sign-up flow — could be a KATHA version, e.g. showing a sample massing diagram
- Red brand-mark + red CTA → single-color discipline (KATHA already does this with pencil-red)

---

## Synthesis — Patterns for KATHA

### Register splits seen across the field

| Register | Examples | KATHA fit |
|---|---|---|
| **White / paper / warm** | Maket, Architechtures, Spacely, Hypar (canvas) | Current `/chat` matches |
| **Dark / charcoal / engineering** | Forma, TestFit, Veras | Worth testing for `/design` |
| **Maximalist gradients** | LookX | Reject — fights the architectural read |

### Common design moves worth taking

1. **Show the output as the hero**, not an illustration (TestFit, Maket, Spacely all do this)
2. **Single accent color** with discipline — orange (TestFit), red (Hypar), pink-red (Maket) — never multiple
3. **List supported file formats explicitly** in the hero or near the CTA (Veras does this brilliantly)
4. **Three-step explainer** (INPUT → AI → OUTPUT) right under the hero — Architechtures
5. **Customer logo strip** when you have 3+ named architects using it (TestFit, Hypar)
6. **Before/after split visuals** to show iteration (Spacely)
7. **Dark sidebar with yellow/red active state** as a working AEC pattern (Forma)

### Common design moves KATHA already does well

- Single accent (pencil-red) ✅
- Architectural metaphor in tokens (paper / ink / hairline / pencil) ✅
- Two-window product split ✅
- Output-driven design (renders, diagrams, drawings as primary) ✅

### Decisions this reference unlocks

1. **Dark sidebar question** — Forma + TestFit + Veras prove dark works for AEC. If you want to revisit this for `/design`, you have precedent.
2. **`/design` hero in empty state** — Hypar's graph-paper background is a strong direction. Could replace the current "STEP 1 / 2 / 3" cards.
3. **Theme picker UX** — Maket's tile-grid pattern beats KATHA's current chips for browsing themes visually.
4. **"Three-icon value props"** — Quick / Deep / Auto could be visualised as three icons under a headline (LookX layout, restrained palette).
