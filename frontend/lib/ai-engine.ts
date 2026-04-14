/**
 * Architecture Knowledge Intelligence Engine
 *
 * Classifies user queries and generates structured, workflow-ready responses
 * following the 7-part Architecture Response Framework.
 */

import type { TopicCategory } from "./ai-prompts";

// ── Topic Classification ───────────────────────────────────────────────────

interface TopicMatch {
  category: TopicCategory;
  keywords: string[];
}

const TOPIC_RULES: TopicMatch[] = [
  {
    category: "vastu-regional",
    keywords: ["vastu", "vaastu", "vastu shastra", "feng shui", "cardinal direction", "brahmasthan", "agni corner", "pooja room placement", "vastu compliant", "vastu tips", "north east", "south west direction", "vastu for"],
  },
  {
    category: "facade-systems",
    keywords: ["facade", "elevation", "exterior", "cladding", "curtain wall", "acp", "hpl", "double skin", "louvre", "jaali", "screen wall", "building envelope"],
  },
  {
    category: "materials-finishes",
    keywords: ["material", "finish", "tile", "stone", "marble", "granite", "wood", "timber", "bamboo", "concrete", "brick", "corten", "terrazzo", "veneer", "laminate", "paint", "plaster", "stucco", "flooring", "cladding material", "glass type", "sustainable material", "eco material", "recycled"],
  },
  {
    category: "structural",
    keywords: ["structure", "structural", "beam", "column", "slab", "foundation", "rcc", "steel frame", "load bearing", "shear wall", "retaining wall", "footing", "pile", "truss", "cantilever", "lintel", "plinth"],
  },
  {
    category: "mep-services",
    keywords: ["mep", "hvac", "plumbing", "electrical", "duct", "pipe", "wiring", "conduit", "drainage", "sewage", "water supply", "fire safety", "sprinkler", "smoke detector", "ventilation", "air conditioning", "exhaust"],
  },
  {
    category: "lighting",
    keywords: ["lighting", "daylight", "natural light", "artificial light", "lux", "lumens", "cove light", "downlight", "skylight", "clerestory", "light shelf", "glare", "task light", "ambient light", "accent light", "facade light", "landscape light"],
  },
  {
    category: "sustainability",
    keywords: ["sustainable", "green building", "passive", "solar", "rainwater", "grey water", "thermal", "insulation", "carbon", "embodied energy", "leed", "griha", "igbc", "net zero", "green roof", "photovoltaic", "eco", "energy efficient", "cross ventilation"],
  },
  {
    category: "space-planning",
    keywords: ["space plan", "layout", "zoning", "circulation", "adjacency", "room size", "carpet area", "built up", "super built", "furniture layout", "ergonomic", "anthropometric", "master plan", "site plan", "floor plan"],
  },
  {
    category: "design-theory",
    keywords: ["design principle", "form follows function", "proportion", "golden ratio", "symmetry", "asymmetry", "hierarchy", "rhythm", "balance", "scale", "contrast", "unity", "emphasis", "pattern", "minimalism", "brutalism", "deconstructivism", "parametric", "organic architecture", "modernism", "postmodern", "art deco", "contemporary"],
  },
  {
    category: "interior-design",
    keywords: ["interior", "furnish", "decor", "kitchen design", "bathroom design", "bedroom design", "living room", "dining", "wardrobe", "modular kitchen", "false ceiling", "wallpaper", "upholstery", "color palette", "mood board", "accent wall", "space feel"],
  },
  {
    category: "construction-docs",
    keywords: ["working drawing", "construction drawing", "detail drawing", "section drawing", "wall section", "staircase detail", "door detail", "window detail", "railing detail", "junction detail", "roof detail", "waterproofing detail", "expansion joint", "specification", "schedule", "door schedule", "window schedule"],
  },
  {
    category: "estimation-boq",
    keywords: ["estimate", "estimation", "boq", "bill of quantities", "cost", "rate", "quantity", "measurement", "sqft cost", "per sqft", "construction cost", "material cost", "labor", "tender", "abstract", "rate analysis"],
  },
  {
    category: "building-codes",
    keywords: ["building code", "nbc", "national building code", "setback", "far", "fsi", "fsr", "coverage", "height restriction", "fire code", "accessibility", "ramp", "ada", "disabled", "parking norm", "open space", "rera", "approval", "sanction plan", "byelaw"],
  },
  {
    category: "academic",
    keywords: ["thesis", "dissertation", "jury", "portfolio", "case study", "presentation sheet", "design studio", "semester project", "concept development", "site analysis project", "architecture college", "student", "assignment", "viva"],
  },
  {
    category: "presentation",
    keywords: ["presentation", "client meeting", "render", "walkthrough", "fly through", "portfolio", "sheet layout", "a1 sheet", "a0 sheet", "panel layout", "design board", "concept board", "material board"],
  },
  {
    category: "rendering",
    keywords: ["render", "3d render", "visualization", "vray", "lumion", "enscape", "twinmotion", "unreal", "realistic render", "photorealistic", "night render", "aerial view", "bird eye", "eye level", "worm eye"],
  },
  {
    category: "site-analysis",
    keywords: ["site analysis", "site visit", "topography", "contour", "soil", "wind direction", "sun path", "context", "surrounding", "approach road", "north direction", "land use", "zoning map"],
  },
  {
    category: "climate-design",
    keywords: ["climate", "tropical", "arid", "temperate", "humid", "cold climate", "hot dry", "warm humid", "composite climate", "monsoon", "solar gain", "heat island", "microclimate", "wind rose", "orientation"],
  },
];

export function classifyTopic(query: string): TopicCategory {
  const q = query.toLowerCase();
  let best: TopicCategory = "general";
  let bestScore = 0;

  for (const rule of TOPIC_RULES) {
    let score = 0;
    for (const kw of rule.keywords) {
      if (q.includes(kw)) {
        // Multi-word matches score higher (more specific)
        score += kw.split(" ").length * 2;
      }
    }
    // Specificity bonus: niche topics (fewer keywords) get a boost when they match
    if (score > 0 && rule.keywords.length < 15) {
      score += 1;
    }
    if (score > bestScore) {
      bestScore = score;
      best = rule.category;
    }
  }

  return best;
}

// ── Structured Response Generator ──────────────────────────────────────────

export function generateArchitectureResponse(query: string): string {
  const topic = classifyTopic(query);
  const generator = RESPONSE_MAP[topic] ?? RESPONSE_MAP["general"];
  return generator(query);
}

type ResponseGenerator = (query: string) => string;

const RESPONSE_MAP: Record<TopicCategory, ResponseGenerator> = {
  "design-theory": generateDesignTheoryResponse,
  "space-planning": generateSpacePlanningResponse,
  "facade-systems": generateFacadeResponse,
  "materials-finishes": generateMaterialsResponse,
  "structural": generateStructuralResponse,
  "mep-services": generateMEPResponse,
  "sustainability": generateSustainabilityResponse,
  "vastu-regional": generateVastuResponse,
  "interior-design": generateInteriorResponse,
  "construction-docs": generateConstructionDocsResponse,
  "estimation-boq": generateEstimationResponse,
  "lighting": generateLightingResponse,
  "building-codes": generateBuildingCodesResponse,
  "academic": generateAcademicResponse,
  "presentation": generatePresentationResponse,
  "rendering": generateRenderingResponse,
  "site-analysis": generateSiteAnalysisResponse,
  "climate-design": generateClimateDesignResponse,
  "general": generateGeneralResponse,
};

// ── Response Generators ────────────────────────────────────────────────────

function generateVastuResponse(_q: string): string {
  return `## Vastu Shastra in Architecture

### Concept
Vastu Shastra is an ancient Indian science of architecture and spatial arrangement that harmonizes buildings with natural forces — sunlight, wind, magnetic fields, and cosmic energy. It is widely applied in residential, commercial, and institutional projects across India.

### Practical Use Cases
| Project Type | Key Vastu Application |
|---|---|
| **Villas** | Main entrance facing East or North, master bedroom in South-West |
| **Apartments** | Pooja room in North-East, kitchen in South-East, toilet never in North-East |
| **Commercial** | Cash counter facing North, owner's cabin in South-West |
| **Hospitals** | Operation theatre orientation, patient ward ventilation |

### Design Best Practices
- **Brahmasthan** (center of the building) should remain open or lightly loaded — avoid placing columns, toilets, or staircases here
- **North & East** walls should have more openings for light and ventilation
- **South & West** walls should be thicker or heavier for thermal mass
- **Main entrance** ideally faces East (sunrise energy) or North (magnetic alignment)
- **Kitchen** placement in the South-East corner (Agni direction) with the cook facing East
- **Master bedroom** in the South-West zone — represents stability and grounding
- **Water elements** (bore well, sump, overhead tank) in the North-East
- **Staircase** should ascend clockwise, placed in South, West, or South-West

### Material / Technical Suggestions
- Use natural stone or earth-toned materials for South-West exteriors (weight and warmth)
- Lighter materials and glass for North and East facades
- Copper elements at the entrance (traditional Vastu enhancement)
- Natural ventilation design aligned with wind direction for the region

### Mistakes to Avoid
- **Toilet in North-East** — considered extremely inauspicious; relocate to North-West or South
- **Kitchen above or below a bedroom** — service conflict and Vastu issue
- **Mirror facing the bed** — redirects energy; avoid or reposition
- **Irregular plot shapes** (L-shape, T-shape) — create Vastu imbalances; use landscaping to regularize
- **Underground water in South-West** — structural and Vastu problem
- **Blindly following Vastu without structural logic** — always balance tradition with engineering

### Visual Reference Suggestions
- Vastu-compliant floor plan diagram with directional zones color-coded
- Site plan showing North alignment, entrance placement, and zone mapping
- Comparison mood board: Traditional Vastu vs Contemporary Vastu-inspired design

### Next Workflow Step
→ **Generate a Vastu-compliant floor plan** in the Image Studio with room placements mapped to cardinal directions
→ Or ask about specific room-level Vastu: bedroom, kitchen, pooja room, staircase`;
}

function generateFacadeResponse(_q: string): string {
  return `## Facade Design Systems

### Concept
The facade is the primary visual identity of a building and its first line of defense against climate. Modern facade design integrates aesthetics, thermal performance, daylighting, ventilation, and structural expression into a unified building envelope system.

### Practical Use Cases
| Project Type | Facade Strategy |
|---|---|
| **Luxury Villas** | Stone cladding + timber battens + large glazing with deep overhangs |
| **Commercial Towers** | Curtain wall systems, double-skin facades, aluminium composite panels |
| **Hospitality** | Feature walls, perforated screens, green walls, dramatic lighting |
| **Institutional** | Exposed concrete + jaali screens + brick textures for durability |
| **Residential Apartments** | Balcony modulation, louver systems, painted plaster with accent cladding |

### Design Best Practices
- **Solid-to-void ratio**: Aim for 55-65% solid on heat-facing facades (West/South in India)
- **Layering**: Create depth with projections, recesses, balconies, and material changes — flat facades feel lifeless
- **Shading devices**: Horizontal for South-facing, vertical for East/West-facing facades
- **Material hierarchy**: Use a maximum of 3 primary materials — one dominant, one secondary, one accent
- **Proportioning**: Follow the golden section or 1:1.5 ratio for window-to-wall proportions
- **Night expression**: Design facade lighting as an integral part — not an afterthought

### Material / Technical Suggestions
| Material | Application | Pros |
|---|---|---|
| **Natural Stone** (granite, sandstone, limestone) | Cladding, feature walls | Timeless, durable, premium feel |
| **Corten Steel** | Accent panels, screens | Self-weathering, industrial-organic |
| **Timber Battens** (teak, IPE, thermo-treated) | Screens, cladding | Warmth, rhythm, biophilic |
| **Perforated Metal** (aluminium, GI) | Jaali, sunscreens | Light filtering, pattern play |
| **HPL Panels** | Rain-screen cladding | Lightweight, color range, low maintenance |
| **ACP** (Aluminium Composite) | Commercial facades | Cost-effective, large format |
| **Exposed Concrete** | Institutional, brutalist | Raw aesthetic, structural honesty |
| **Glass** (DGU, tinted, fritted) | Vision panels, curtain walls | Transparency, daylighting |

### Mistakes to Avoid
- **West-facing glass walls without shading** — extreme heat gain in tropical climates
- **Single-material facades** — monotonous; always add relief through texture or depth changes
- **Ignoring rain detailing** — water staining ruins facades faster than anything; design drip edges and water channels
- **Flat facades with applied decoration** — feels cheap; create real depth with structural modulation
- **Mismatched scale** — large buildings with small domestic-scale elements (or vice versa)

### Visual Reference Suggestions
- Facade material mood board with 3-4 material samples, textures, and color palette
- Elevation drawing showing material mapping and shading analysis
- 3D render at eye-level showing street-level facade presence
- Night render showing lighting expression

### Next Workflow Step
→ **Generate a facade elevation** in Image Studio — select "Elevation Drawing" as the output type
→ Or ask about specific facade topics: material selection, shading design, curtain wall detailing, facade lighting`;
}

function generateMaterialsResponse(_q: string): string {
  return `## Building Materials & Finishes

### Concept
Material selection is one of the most impactful decisions in architecture — it defines visual character, construction cost, structural performance, thermal comfort, maintenance burden, and sustainability footprint. Good material choices balance aesthetics, performance, budget, and availability.

### Practical Use Cases
| Zone | Material Priority |
|---|---|
| **Exterior walls** | Durability, weather resistance, thermal mass, aesthetic |
| **Interior walls** | Finish quality, acoustic performance, maintenance |
| **Flooring** | Wear resistance, slip rating, aesthetic, warmth/coolness |
| **Roof** | Waterproofing, insulation, load capacity |
| **Wet areas** | Water resistance, anti-microbial, easy cleaning |
| **Facade** | UV resistance, dimensional stability, fire rating |

### Design Best Practices

**Selection Framework (5 criteria):**
1. **Performance** — Structural capacity, fire rating, thermal conductivity
2. **Durability** — Lifespan, maintenance cycle, weather resistance
3. **Aesthetics** — Texture, color, scale, pattern, aging character
4. **Sustainability** — Embodied carbon, recyclability, local sourcing, VOC levels
5. **Cost** — Material cost + installation cost + lifecycle maintenance cost

**Material Palette Rule:**
- Limit to **3-4 primary materials** per project for visual coherence
- One **dominant** (60%), one **secondary** (25%), one **accent** (15%)

### Material / Technical Suggestions

**Sustainable Alternatives:**
| Conventional | Sustainable Alternative |
|---|---|
| RCC columns | Glulam timber or steel with recycled content |
| Clay bricks | Compressed earth blocks (CEB), fly ash bricks |
| Granite flooring | Kota stone, terrazzo with recycled aggregate |
| Plywood | Bamboo board, particle board (FSC certified) |
| Cement plaster | Lime plaster (breathable, lower carbon) |
| Glass wool insulation | Sheep wool, cork, recycled denim |

**Premium Finishes Guide:**
- **Living areas**: Italian porcelain (1200x600), hardwood or engineered wood
- **Bathrooms**: Large format anti-skid tiles, wall-hung sanitaryware
- **Kitchens**: Quartz/Dekton countertops, acrylic or membrane shutters
- **Facade accents**: Natural stone, thermally modified wood, cor-ten steel

### Mistakes to Avoid
- **Choosing materials purely on looks** — always verify performance specs (water absorption, hardness, fire rating)
- **Ignoring thermal properties in facades** — high-conductivity materials without insulation cause energy waste
- **Using indoor materials outdoors** — many tiles, woods, and paints are not UV/weather rated
- **Mixing too many materials** — creates visual chaos; discipline the palette
- **Forgetting maintenance** — beautiful materials that stain or degrade are worse than modest durable ones

### Visual Reference Suggestions
- Material mood board with actual texture samples, dimensions, and supplier references
- Interior finish schedule table (room-by-room specification)
- Facade material mapping on an elevation drawing
- 3D close-up render showing material junctions and details

### Next Workflow Step
→ **Create a material mood board** in Image Studio — select "Concept / Mood Board" as the output type
→ Or ask about specific material topics: flooring comparison, wall finish options, sustainable alternatives, cost per sqft`;
}

function generateSpacePlanningResponse(_q: string): string {
  return `## Space Planning & Layout Design

### Concept
Space planning is the strategic organization of rooms, circulation paths, and activity zones within a building footprint. It balances functional adjacencies, natural light access, ventilation, privacy, structural grid alignment, and user behavior patterns. Good space planning is invisible — bad space planning is felt every day.

### Practical Use Cases
| Project Type | Key Planning Concerns |
|---|---|
| **2BHK Apartment** (800-1100 sqft) | Compact efficiency, dual-use spaces, storage integration |
| **3BHK Villa** (1800-2500 sqft) | Public-private zoning, servant quarters, parking integration |
| **Office** | Open plan vs cabin ratio, meeting room access, breakout zones |
| **Hospital** | Patient flow, sterile zones, emergency access, wayfinding |
| **School** | Classroom cluster + play area adjacency, admin separation |
| **Restaurant** | Kitchen-dining adjacency, service vs guest circulation, acoustics |

### Design Best Practices

**Zoning Principles:**
- **Public zone** (living, dining, foyer) — closest to entrance, most open
- **Private zone** (bedrooms, study) — away from entrance, quieter
- **Service zone** (kitchen, utility, toilets) — clustered for plumbing efficiency
- **Transition zone** (corridors, lobbies) — minimized for usable area

**Dimensional Standards (Residential):**
| Room | Minimum Size | Recommended |
|---|---|---|
| Master Bedroom | 120 sqft / 11 sqm | 150-180 sqft |
| Second Bedroom | 100 sqft / 9.3 sqm | 120-140 sqft |
| Living Room | 150 sqft / 14 sqm | 200-250 sqft |
| Kitchen | 80 sqft / 7.4 sqm | 100-120 sqft |
| Bathroom | 35 sqft / 3.25 sqm | 45-55 sqft |
| Dining | 100 sqft / 9.3 sqm | 120-150 sqft |

**Circulation:**
- Corridors: minimum 1050mm (3'6") clear width residential, 1500mm (5') commercial
- Staircase: minimum 900mm (3') width residential, 1200mm (4') public
- Aim for **circulation area below 20%** of total floor area

### Mistakes to Avoid
- **Dead-end corridors** — waste space and create dark zones
- **Bathroom doors opening into living/dining** — privacy and odor issues
- **Kitchen far from dining** — creates service inefficiency
- **Bedrooms on the West side** without shading — excessive heat in Indian climates
- **Ignoring furniture clearances** — a 10x12 bedroom feels tiny with a king bed, two side tables, and a wardrobe

### Visual Reference Suggestions
- Bubble diagram showing room adjacencies and zone relationships
- Floor plan with furniture layout and circulation paths marked
- Zoning diagram color-coded by public/private/service
- Sun path overlay showing light access to each room

### Next Workflow Step
→ **Generate a floor plan layout** in Image Studio — select "Floor Plan" as the output type
→ Or ask about specific planning: kitchen layout types, bathroom planning, staircase design, parking layout`;
}

function generateStructuralResponse(_q: string): string {
  return `## Structural Systems in Architecture

### Concept
Structural systems are the skeleton of a building — they transfer all loads (dead, live, wind, seismic) safely to the ground. The choice of structural system directly impacts column-free spans, floor-to-floor height, facade possibilities, cost, and construction speed. Architects must understand structure to design intelligently.

### Practical Use Cases
| System | Best For | Typical Span |
|---|---|---|
| **Load-bearing walls** | Low-rise residential (1-3 floors) | 4-5m |
| **RCC Frame** (beam-column) | Most common for apartments, commercial up to 12 floors | 5-8m |
| **Flat slab** | Commercial, parking, open plans needing flexible layouts | 6-9m |
| **Steel frame** | Industrial, high-rise, large-span commercial | 12-30m+ |
| **Pre-engineered (PEB)** | Warehouses, factories, exhibition halls | 30-60m |
| **Post-tensioned** | Long-span commercial, bridges, special structures | 10-15m |

### Design Best Practices
- **Grid discipline**: Maintain a regular structural grid (e.g., 6m x 6m, 7.5m x 7.5m) — irregular grids increase cost by 15-30%
- **Column placement**: Never place columns in the middle of rooms; push to walls and corners
- **Beam depth rule of thumb**: Span/12 to Span/15 for simply supported; Span/15 to Span/20 for continuous
- **Slab thickness**: 125-150mm for residential, 150-200mm for commercial (RCC flat slab)
- **Expansion joints**: Required every 45m in RCC buildings (IS 456)
- **Coordinate early**: Structural and architectural plans must align from Day 1 — retrofitting is expensive

### Material / Technical Suggestions
- **M25-M30 concrete** for most residential and commercial (M40+ for high-rise)
- **Fe500D TMT bars** — standard reinforcement grade in India
- **Structural steel**: Use IS 2062 Grade E250/E350 for frame structures
- **Waterproofing at foundation**: Bituminous membrane or crystalline admixture for basements

### Mistakes to Avoid
- **Designing architecture without considering structure** — leads to expensive structural gymnastics
- **Columns misaligned floor to floor** — creates transfer beams (costly, risky)
- **Ignoring seismic zones** — India has 4 seismic zones; design accordingly per IS 1893
- **Overhanging slabs without design** — cantilevers beyond 1.5m need careful structural design
- **Plumbing through beams** — never cut or core through structural beams without engineer approval

### Visual Reference Suggestions
- Structural layout plan showing column grid, beam layout, and slab type
- Wall section detail showing foundation to roof structure
- 3D structural wireframe showing frame system

### Next Workflow Step
→ **Generate a structural layout plan** in Image Studio — select "Structural Diagram" as the output type
→ Or ask about foundations, slab design, retaining walls, or seismic design`;
}

function generateMEPResponse(_q: string): string {
  return `## MEP Systems (Mechanical, Electrical, Plumbing)

### Concept
MEP systems are the life-support infrastructure of a building. They account for 30-40% of total construction cost and require careful coordination with architectural and structural plans. Early MEP integration prevents costly clashes and rework during construction.

### Practical Use Cases
| System | Key Components |
|---|---|
| **Plumbing** | Water supply (cold/hot), drainage, sewage, rainwater, fire hydrant |
| **Electrical** | Power distribution, lighting circuits, LV/HV panels, earthing, DG backup |
| **HVAC** | Air conditioning, ventilation, exhaust, fresh air handling |
| **Fire safety** | Detection (smoke/heat), suppression (sprinklers), alarms, escape lighting |
| **Low voltage** | CCTV, access control, intercom, data/networking, home automation |

### Design Best Practices

**Plumbing:**
- Stack wet areas vertically (bathroom above bathroom) — reduces pipe runs by 40%
- Minimum 1% slope for drainage pipes (1:100 gradient)
- Hot water pipes need insulation if run exceeds 5m
- Provide shaft access panels for maintenance — never bury pipes without access

**Electrical:**
- Residential load: 3-5 kW per apartment; commercial: 50-80 W/sqm
- DB (distribution board) near the entry, within 3m of the main supply
- Separate circuits for lighting, power, AC, and kitchen appliances
- Earthing: minimum 2 earth pits per building (IS 3043)

**HVAC:**
- 1 TR (ton of refrigeration) per 100-120 sqft for standard office/residential
- Ceiling void: minimum 300mm for ducted AC; 150mm for cassette units
- Fresh air requirement: 10-15 CFM per person (ASHRAE 62.1)
- Exhaust fans in every bathroom and kitchen — code requirement

### Mistakes to Avoid
- **No MEP coordination before construction** — #1 cause of site rework
- **Drainage pipes through living room ceiling** — route through service areas
- **AC outdoor unit on bedroom wall** — noise and vibration transfer
- **Inadequate shaft sizes** — shafts need space for pipes + access + future expansion
- **Ignoring fire code** — sprinklers, smoke detectors, and fire exits are mandatory per NBC

### Visual Reference Suggestions
- MEP coordination drawing showing all 3 systems overlaid
- Riser diagram for plumbing/electrical
- HVAC duct layout plan
- Shaft section detail

### Next Workflow Step
→ **Generate an MEP layout** in Image Studio — select "MEP Drawings" as the output type
→ Or ask about specific systems: HVAC sizing, electrical load calculation, plumbing riser design`;
}

function generateSustainabilityResponse(_q: string): string {
  return `## Sustainable Architecture & Green Design

### Concept
Sustainable architecture minimizes environmental impact while maximizing occupant comfort across the entire building lifecycle — from material sourcing through construction, operation, and eventual demolition. It integrates passive design strategies, efficient active systems, renewable energy, and responsible material choices.

### Practical Use Cases
| Strategy | Application |
|---|---|
| **Passive cooling** | Courtyard houses, cross-ventilation apartments, earth-sheltered structures |
| **Daylighting** | Atriums in commercial, light wells in deep-plan buildings, clerestory schools |
| **Rainwater harvesting** | Mandatory in most Indian states for plots > 100 sqm |
| **Solar energy** | Rooftop PV for apartments, BIPV facade panels for commercial |
| **Green roofs** | Hospitals, commercial, institutional — reduces heat island + manages stormwater |
| **Recycled materials** | Fly ash bricks, recycled steel, reclaimed wood, recycled aggregate |

### Design Best Practices

**Passive Design Priorities (cost-free or low-cost):**
1. **Orientation** — Long axis East-West reduces solar heat gain by 20-30%
2. **Cross-ventilation** — Openings on opposite walls; inlet area = 1/3 of outlet for best airflow
3. **Shading** — External shading devices are 5x more effective than internal blinds
4. **Thermal mass** — Heavy walls (brick, concrete, stone) absorb heat during the day, release at night
5. **Landscaping** — Trees on West side reduce AC load by 15-25%

**Rating Systems:**
| System | Region | Levels |
|---|---|---|
| **GRIHA** | India | 1-5 stars |
| **IGBC** | India | Certified, Silver, Gold, Platinum |
| **LEED** | International | Certified, Silver, Gold, Platinum |
| **BREEAM** | UK/International | Pass to Outstanding |

### Material / Technical Suggestions
- **Fly ash bricks** instead of clay bricks — 30% lower embodied energy
- **AAC blocks** — excellent thermal insulation (U-value 0.7 W/m²K vs 2.4 for solid brick)
- **Low-E double glazed units** — reduce heat gain by 50% vs single glazing
- **Bamboo** — 3-5 year growth cycle vs 25-50 years for timber
- **Lime plaster** — lower carbon than cement plaster, breathable

### Mistakes to Avoid
- **All-glass facades in tropical climates** — creates greenhouse effect; HVAC costs skyrocket
- **Greenwashing** — adding plants without addressing energy, water, and material fundamentals
- **Ignoring embodied carbon** — operational efficiency means nothing if materials are carbon-intensive
- **Over-relying on technology** — passive design first, active systems second

### Visual Reference Suggestions
- Sun path diagram overlaid on site plan
- Cross-section showing passive ventilation and daylighting strategies
- Material lifecycle comparison chart
- Green building concept mood board

### Next Workflow Step
→ **Generate a sustainability concept diagram** in Image Studio
→ Or ask about: passive cooling techniques, rainwater system design, solar panel sizing, GRIHA documentation`;
}

function generateLightingResponse(_q: string): string {
  return `## Architectural Lighting Design

### Concept
Lighting design in architecture operates on two levels: **daylighting** (maximizing natural light to reduce energy and improve wellbeing) and **artificial lighting** (creating layers of illumination for function, mood, and visual hierarchy). Great architects treat light as a building material.

### Practical Use Cases
| Space Type | Lux Level (IS 3646) | Strategy |
|---|---|---|
| **Living room** | 150-300 lux | Ambient + accent, warm white (2700-3000K) |
| **Kitchen** | 300-500 lux | Task lighting on countertops, general ambient |
| **Bedroom** | 100-150 lux | Layered dimming, bedside task, cove ambient |
| **Office** | 300-500 lux | Uniform, glare-free, 4000K neutral white |
| **Hospital ward** | 100-200 lux | Indirect, patient-friendly, circadian support |
| **Classroom** | 300-500 lux | Even distribution, minimize board glare |
| **Retail** | 500-1000 lux | High CRI (>90), accent on merchandise |

### Design Best Practices

**Daylighting Strategies:**
- **Window-to-floor ratio**: 15-25% for good daylight, 25-40% for daylight-dominant spaces
- **Daylight penetration**: Natural light reaches 1.5-2x the window head height into a room
- **Light shelves**: Bounce light deeper; effective for South-facing facades
- **Skylights**: 3-5% of roof area provides adequate daylight for top-floor spaces
- **Avoid direct glare**: Use diffused glass, louvers, or curtains on East/West facades

**Artificial Lighting Layers:**
1. **Ambient** — Cove lighting, recessed downlights, indirect ceiling wash
2. **Task** — Under-cabinet lights, desk lamps, reading lights
3. **Accent** — Wall washers, picture lights, directional spots
4. **Decorative** — Chandeliers, pendant fixtures, sculptural lights

### Mistakes to Avoid
- **Single overhead light source** — creates flat, institutional feel; always layer
- **Wrong color temperature** — mixing 3000K and 6500K in one space looks unpleasant
- **Ignoring CRI** (Color Rendering Index) — cheap LEDs with CRI < 80 make materials look dull
- **No dimming capability** — fixed bright lighting is inflexible; install dimmers in all residential spaces
- **Forgetting facade lighting** — buildings disappear at night; plan exterior lighting from the start

### Visual Reference Suggestions
- Lighting layout plan with fixture types and lux distribution
- Section showing daylight penetration analysis
- Night render showing facade and landscape lighting
- Mood board with fixture styles and light temperatures

### Next Workflow Step
→ **Generate a lighting concept render** in Image Studio — try both day and night versions
→ Or ask about: lux calculation, fixture selection, facade lighting design, smart lighting controls`;
}

function generateInteriorResponse(_q: string): string {
  return `## Interior Design & Space Styling

### Concept
Interior design transforms architectural spaces into lived experiences. It integrates spatial planning, material finishes, color psychology, furniture selection, lighting, and environmental comfort into a cohesive design narrative. Modern interiors balance aesthetics with ergonomics, maintenance, and budget.

### Practical Use Cases
| Room | Key Design Focus |
|---|---|
| **Living room** | Seating layout, focal point (TV/fireplace), natural light, accent wall |
| **Master bedroom** | Bed orientation, wardrobe integration, lighting layers, privacy |
| **Kitchen** | Work triangle (sink-stove-fridge), counter height (850-900mm), ventilation |
| **Bathroom** | Wet-dry zoning, fixture spacing, waterproofing, anti-skid flooring |
| **Home office** | Desk orientation (avoid back to door), task lighting, acoustic comfort |
| **Dining** | Table size per person (600mm width), pendant height (750mm above table) |

### Design Best Practices

**Color & Material Rules:**
- **60-30-10 rule**: 60% dominant color (walls), 30% secondary (furniture), 10% accent (decor)
- **Light colors** expand small spaces; dark colors add intimacy to large ones
- **Maximum 3 flooring materials** in a home — maintain visual continuity
- **Match undertones**: Warm walls (cream, beige) with warm wood (walnut, teak); cool walls (grey, white) with cool materials (marble, steel)

**Furniture Clearances:**
| Situation | Minimum Clearance |
|---|---|
| Walking path | 900mm (3 ft) |
| Dining chair pullback | 750mm from table edge to wall |
| Coffee table to sofa | 450mm (18 inches) |
| Bed to wall (one side) | 600mm for making the bed |
| Kitchen counter depth | 600mm standard |

### Mistakes to Avoid
- **Over-furnishing** — less is more; every piece should earn its place
- **Ignoring scale** — oversized furniture in small rooms (or vice versa) breaks proportions
- **Matching everything** — wood tones, metals, and textures should complement, not match identically
- **Neglecting ventilation in kitchens** — chimney/exhaust is mandatory, not optional
- **Wrong tile grout color** — dark grout with light tiles shows every stain

### Visual Reference Suggestions
- Interior layout plan with furniture dimensions
- Material and color palette mood board
- 3D render showing key living spaces
- Furniture detail drawings with custom joinery

### Next Workflow Step
→ **Generate an interior visualization** in Image Studio — select "Interior Layout Plan" or "3D Render"
→ Or ask about: modular kitchen design, bathroom layout, false ceiling design, color palettes`;
}

function generateConstructionDocsResponse(_q: string): string {
  return `## Construction & Working Drawings

### Concept
Working drawings are the legal and technical documents that translate an architectural design into buildable instructions. They include dimensioned plans, sections, elevations, detail drawings, schedules, and specifications. Accuracy here directly determines construction quality, cost control, and regulatory compliance.

### Drawing Types Required
| Drawing | Purpose |
|---|---|
| **Floor plans** (1:100) | Room layout, dimensions, door/window positions, furniture layout |
| **Elevations** (1:100) | External appearance, material specification, heights |
| **Sections** (1:50 or 1:100) | Floor-to-floor height, slab levels, beam depths, staircase profile |
| **Site plan** (1:200 or 1:500) | Building position, setbacks, parking, landscaping, services |
| **Detail drawings** (1:10 or 1:20) | Wall sections, window sills, staircase details, railing, waterproofing |
| **Door & window schedule** | Type, size, material, hardware for every opening |
| **Electrical layout** | Switch, socket, light point positions per room |
| **Plumbing layout** | Fixture positions, pipe routing, shaft locations |
| **Structural drawings** | Column layout, beam layout, footing details, reinforcement schedules |

### Design Best Practices
- **Dimension everything** — if it's not dimensioned, it will be built wrong
- **Running dimensions** from a common reference point — avoids cumulative errors
- **Level marks** on every section and elevation — +0.00 at plinth level (common Indian practice)
- **Layer discipline**: Separate layers for walls, dimensions, furniture, electrical, plumbing, text
- **Title block**: Drawing number, scale, date, revision number, project name, architect's stamp
- **Cross-reference**: Every section line, detail callout, and elevation indicator must reference a sheet number

### Mistakes to Avoid
- **Missing dimensions** — the most common construction site complaint
- **Scale inconsistency** — plans at 1:100, details at 1:10; never mix on the same sheet
- **No revision tracking** — always date and number revisions; superseded drawings cause disasters
- **Bathroom details missing** — waterproofing, falls, drain positions are critical
- **Not coordinating with structural and MEP** — clashes discovered on site are expensive

### Visual Reference Suggestions
- Standard wall section from foundation to parapet (1:20)
- Door and window detail drawings
- Staircase section showing tread, riser, railing details
- Typical bathroom waterproofing section

### Next Workflow Step
→ **Generate a working drawing sheet** in Image Studio — select "Working Drawings" as the output type
→ Or ask about: wall section details, staircase detailing, door schedule template, waterproofing specifications`;
}

function generateEstimationResponse(_q: string): string {
  return `## Construction Estimation & BOQ

### Concept
A Bill of Quantities (BOQ) is a systematic list of materials, labor, and services required to construct a building, along with their measured quantities and estimated costs. It is the financial backbone of any construction project — used for budgeting, tendering, vendor comparison, and cost control.

### Estimation Workflow
1. **Quantity takeoff** — Measure quantities from drawings (area, volume, running meters, numbers)
2. **Rate application** — Apply market rates or DSR/CPWD rates to each item
3. **Abstract preparation** — Summarize by trade/category (civil, electrical, plumbing, finishing)
4. **Contingency** — Add 5-10% for unforeseen items
5. **Escalation** — Factor material price inflation for project duration

### Cost Benchmarks (India, 2024-25)
| Category | Budget Range | Standard Range | Premium Range |
|---|---|---|---|
| **Residential** | ₹1,400-1,800/sqft | ₹2,000-2,800/sqft | ₹3,500-6,000/sqft |
| **Commercial** | ₹1,800-2,500/sqft | ₹2,800-4,000/sqft | ₹4,500-8,000/sqft |
| **Interior fit-out** | ₹800-1,200/sqft | ₹1,500-2,500/sqft | ₹3,000-5,000/sqft |

### Design Best Practices

**BOQ Categories:**
| Category | Includes |
|---|---|
| **Civil works** | Excavation, foundation, RCC frame, masonry, plastering |
| **Finishing** | Flooring, wall cladding, painting, false ceiling |
| **Electrical** | Wiring, switches, panels, light fixtures, earthing |
| **Plumbing** | Pipes, fixtures, tanks, pumps, STP |
| **HVAC** | AC units, ducting, insulation, controls |
| **Furniture** | Modular kitchen, wardrobes, custom joinery |
| **External works** | Landscaping, paving, boundary wall, gate |

**Rate Analysis Logic:**
- Material cost (40-50% of item) + Labor cost (25-35%) + Overheads (10-15%) + Profit (5-10%)
- Always verify local material rates — they vary by city by 15-30%

### Mistakes to Avoid
- **Estimating from concept drawings** — use only dimensioned working drawings for accurate BOQ
- **Forgetting hidden costs** — approvals, soil testing, temporary works, water/electricity charges
- **Not updating rates quarterly** — steel, cement, and sand prices fluctuate significantly
- **Lump-sum estimation** — always break down to item level; lump sums hide errors

### Visual Reference Suggestions
- BOQ spreadsheet template with categories and units
- Cost comparison chart across material grades
- Pie chart showing cost distribution (civil 45%, finishing 20%, MEP 25%, furniture 10%)

### Next Workflow Step
→ Use the **Estimation Terminal** (bottom panel in Image Studio) for detailed calculations
→ Or ask about: rate analysis for specific items, cost optimization strategies, tender document preparation`;
}

function generateBuildingCodesResponse(_q: string): string {
  return `## Building Codes & Regulations

### Concept
Building codes are the legal framework that governs construction safety, setbacks, height limits, fire protection, accessibility, and environmental compliance. In India, the primary references are the **National Building Code (NBC 2016)**, local Development Control Regulations (DCR), and state-specific building byelaws.

### Key Regulatory Parameters
| Parameter | Definition | Typical Range |
|---|---|---|
| **FAR / FSI** | Floor Area Ratio — total built-up area / plot area | 1.0 to 4.0 (varies by zone) |
| **Ground coverage** | Building footprint / plot area | 30-60% |
| **Setbacks** | Distance from boundary to building face | 3m-12m depending on plot and road width |
| **Height restriction** | Maximum building height allowed | Based on road width and fire zone |
| **Parking** | Car + two-wheeler spaces per dwelling unit or per sqm | Varies by DCR |
| **Open space** | Required recreational/garden area | 10-25% of plot |

### Design Best Practices
- **Check local DCR first** — national codes give minimums; local rules are often stricter
- **Calculate FSI early** — determines how much you can build; impacts entire design
- **Fire safety compliance**: Buildings above 15m need firefighting shafts, refuge areas, sprinklers (NBC Part 4)
- **Accessibility**: Ramps at every level change, minimum 1 accessible toilet per floor, 1500mm corridor minimum for wheelchair
- **Sanction plan requirements**: Typically need site plan, floor plans, elevations, sections, structural certificate, soil report

### Mistakes to Avoid
- **Building first, seeking approval later** — illegal and causes demolition orders
- **Miscalculating FSI** — common error; always exclude staircase, lift, utility shafts from FSI as per local DCR
- **Ignoring fire setbacks** — adjacent buildings too close is both illegal and dangerous
- **Inaccessible buildings** — accessibility compliance is now mandatory, not optional

### Next Workflow Step
→ Ask about specific codes: fire safety norms, accessibility requirements, FSI calculation, parking norms
→ Or provide your plot dimensions and local DCR zone — I can help calculate permissible built-up area`;
}

function generateDesignTheoryResponse(_q: string): string {
  return `## Architectural Design Theory & Principles

### Concept
Design theory provides the intellectual and aesthetic framework for architectural decision-making. These principles — developed over millennia from Vitruvius to contemporary parametricism — guide how architects create spaces that are beautiful, functional, structurally sound, and emotionally resonant.

### Core Design Principles
| Principle | Definition | Architectural Application |
|---|---|---|
| **Proportion** | Mathematical relationship between parts and whole | Golden ratio (1:1.618) in facades, room dimensions, window sizing |
| **Scale** | Perceived size relative to human body and context | Monumental scale for institutions, intimate scale for homes |
| **Hierarchy** | Organizing elements by importance | Grand entrance > circulation > service spaces |
| **Rhythm** | Regular repetition creating visual pattern | Column spacing, window modules, facade bays |
| **Balance** | Visual equilibrium — symmetrical or asymmetrical | Symmetry for formal (institutional), asymmetry for dynamic (residential) |
| **Contrast** | Juxtaposition of opposing elements | Solid vs void, heavy vs light, rough vs smooth |
| **Unity** | Coherence through consistent design language | Material palette, proportional system, stylistic consistency |

### Design Movements (Key Reference)
- **Modernism** — Le Corbusier's 5 points, Mies van der Rohe "less is more", pure geometric forms
- **Brutalism** — Raw concrete, massive forms, structural honesty (Chandigarh, Barbican)
- **Deconstructivism** — Fragmented geometry, challenging conventions (Gehry, Hadid, Libeskind)
- **Minimalism** — Reduction to essentials, "architecture of silence" (Tadao Ando, John Pawson)
- **Parametric** — Algorithm-driven form, organic curves, digital fabrication (Zaha Hadid Architects)
- **Biophilic** — Nature-integrated design, improving health and wellbeing through natural elements

### Design Best Practices
- **Start with a strong concept** — every design decision should trace back to one clear idea
- **Study precedents** — analyze 3-5 relevant case studies before starting any design
- **Sketch before CAD** — hand sketching develops spatial thinking faster than software
- **Design in section** — plan alone never reveals the full spatial experience
- **Model at multiple scales** — site model (1:500), building model (1:200), detail model (1:50)

### Mistakes to Avoid
- **Copying without understanding** — Pinterest aesthetics without spatial logic
- **Ignoring context** — a building that works in Scandinavia may fail in tropical India
- **Over-designing** — complexity without purpose is visual noise
- **Forgetting the human** — architecture is for people, not photographs

### Visual Reference Suggestions
- Concept diagram showing the core design idea
- Precedent study comparison board
- Proportion analysis overlaid on an elevation
- Parti diagram (essential form diagram)

### Next Workflow Step
→ Ask about a specific design movement, architect, or principle for deeper analysis
→ Or describe your project brief — I'll help develop the design concept`;
}

function generateAcademicResponse(_q: string): string {
  return `## Architecture Academic Support

### Concept
Architecture education revolves around design studios, technical subjects, and jury presentations. Whether you're developing a thesis concept, preparing a semester project, or building a portfolio, the process follows a structured design methodology from research through presentation.

### Key Academic Workflows

**Thesis / Final Year:**
1. **Topic selection** — Choose a socially relevant, architecturally rich program (museum, transit hub, community center, adaptive reuse)
2. **Literature review** — Study 5-10 case studies in depth; extract design principles
3. **Site selection & analysis** — Justify site choice; document context, climate, access, constraints
4. **Design development** — Concept → Zoning → Plans → Sections → 3D → Detailing
5. **Presentation** — Sheet layout, physical model, digital walkthrough, design statement

**Portfolio Building:**
- Show process, not just finished products — sketches, iterations, diagrams
- 3-5 strong projects are better than 10 weak ones
- Consistent graphic language across all sheets
- Include a variety: residential, public, urban, interior, competition entries
- Sheet size: A3 landscape for digital portfolios, A1 for physical presentations

### Design Best Practices
- **Start every project with site analysis** — climate, sun path, wind, context, access, views
- **Develop a clear concept** in 1-2 sentences before touching CAD
- **Use diagrams** to explain zoning, circulation, structure, environmental response
- **Design in section** — the best architectural ideas are revealed in section, not plan
- **Build physical models** — even rough study models develop spatial understanding

### Jury Presentation Tips
- Open with the **problem statement**, not the solution
- Explain your **design process** — juries value thinking, not just the final output
- Keep text minimal on sheets — let drawings speak
- Practice the 5-minute pitch — concept, site, plans, sections, key detail, one render
- Prepare for tough questions: structural logic, code compliance, cost feasibility

### Mistakes to Avoid
- **Starting with 3D renders** before resolving the plan — renders of bad plans are still bad architecture
- **Over-rendering** — photorealistic renders without solid spatial design is lipstick on a pig
- **Copying Pinterest without attribution or understanding** — juries can tell
- **Ignoring climate and context** — generic designs that could be anywhere score poorly
- **Last-minute panic sheets** — always maintain a weekly schedule

### Visual Reference Suggestions
- Site analysis sheet with climate data, context photos, mapping
- Concept development board showing evolution from idea to form
- Sheet layout template (A1 landscape with title strip, drawing zones, text blocks)
- Portfolio cover page and table of contents design

### Next Workflow Step
→ Tell me your **thesis topic or project brief** and I'll help develop the concept
→ Or ask about: case study analysis method, sheet layout design, model-making tips, jury preparation`;
}

function generatePresentationResponse(_q: string): string {
  return `## Architectural Presentation & Client Communication

### Concept
Architectural presentations bridge the gap between technical design and client understanding. Whether it's a jury review, client meeting, or competition entry, the presentation must tell a compelling story — from site context through design concept to spatial experience — in a clear visual hierarchy.

### Presentation Types
| Format | Audience | Focus |
|---|---|---|
| **Client presentation** | Non-technical clients | Renders, material boards, lifestyle imagery, cost overview |
| **Design jury** | Academics/peers | Process, concept diagrams, technical drawings, critical analysis |
| **Competition entry** | Jury panel | Strong narrative, unique concept, clear graphics, bold vision |
| **Contractor briefing** | Builder/contractor | Working drawings, specifications, schedules, details |
| **Marketing collateral** | Buyers/investors | Hero renders, floor plan brochures, amenity highlights |

### Design Best Practices

**Sheet Layout (A1 Presentation):**
- **Visual hierarchy**: Hero image (40% of sheet) → Support drawings (35%) → Text & diagrams (25%)
- **Reading direction**: Top-left to bottom-right (Z-pattern) or left-to-right narrative flow
- **White space**: Minimum 15% of sheet should be empty — breathing room improves readability
- **Consistent grid**: Use a 6 or 8 column grid; snap everything to it
- **Typography**: Maximum 2 font families; hierarchy through weight and size, not variety

**Client Meeting Essentials:**
1. Start with **site context** — clients connect with place
2. Show the **floor plan with furniture** — they understand rooms, not abstract geometry
3. Use **eye-level renders** — bird's eye views are for architects, not clients
4. Present **material samples physically** — screens don't show texture
5. End with **next steps and timeline** — clients want action, not just art

### Mistakes to Avoid
- **Too many drawings, no hierarchy** — a cluttered presentation is an unread presentation
- **Renders without plans** — beautiful images without spatial logic raise client doubts
- **Using technical jargon** — "fenestration ratio" means nothing to a homeowner; say "window placement"
- **No physical material samples** — screen colors are unreliable; always bring samples
- **Presenting options without a recommendation** — guide the client; don't overwhelm them

### Visual Reference Suggestions
- Presentation sheet layout template (A1 landscape)
- Client-facing mood board with renders + materials + color palette
- Before/after comparison for renovation projects
- Animated walkthrough storyboard

### Next Workflow Step
→ **Generate presentation-quality renders** in Image Studio — select "3D Render" for client visuals
→ Or ask about: sheet layout design, render composition tips, client meeting structure, competition panel design`;
}

function generateRenderingResponse(_q: string): string {
  return `## Architectural Visualization & Rendering

### Concept
Architectural rendering translates 3D design models into photorealistic or stylized images that communicate spatial quality, material character, lighting mood, and environmental context. It serves as the primary visual communication tool for clients, competitions, and marketing.

### Rendering Software Ecosystem
| Software | Strength | Render Time | Learning Curve |
|---|---|---|---|
| **Lumion** | Real-time, landscapes, animation | Instant-minutes | Easy |
| **Enscape** | Real-time, Revit/SketchUp plugin | Instant | Easy |
| **Twinmotion** | Real-time, Unreal Engine based | Instant-minutes | Easy |
| **V-Ray** | Photorealistic quality, versatile | Minutes-hours | Medium |
| **Corona** | Clean, soft renders, interior focus | Minutes-hours | Medium |
| **Unreal Engine** | Real-time ray tracing, VR-ready | Real-time | Hard |
| **D5 Render** | AI-powered, real-time quality | Instant-minutes | Easy |

### Render Composition Best Practices
- **Eye-level shots** for client presentations — human perspective creates connection
- **2-point perspective** for exterior elevations — avoid 3-point unless dramatic effect intended
- **Rule of thirds** for composition — place the building at 1/3 marks, not dead center
- **Human figures** (entourage) for scale — always include people, cars, trees
- **Golden hour lighting** (sunrise/sunset) creates warm, inviting atmosphere
- **Overcast sky** for material-focused renders — even lighting shows true colors

### Camera Angles for Architecture
| Angle | Use Case |
|---|---|
| **Eye-level** (1.6m height) | Street presence, entrance experience |
| **Aerial / bird's eye** | Massing, site context, roof design |
| **Worm's eye** | Dramatic height, tower projects |
| **Interior** (seated height ~1.2m) | Living spaces, showroom feel |
| **Drone-style** (15-30m) | Neighborhood context, landscape |

### Mistakes to Avoid
- **Over-saturated colors** — architecture renders should feel real, not like video game art
- **Wrong scale trees/people** — a 3m tall person destroys the entire render
- **Neglecting the ground plane** — grass, paving, shadows on the ground anchor the building
- **Flat lighting** — avoid noon sun directly overhead; morning or evening light adds depth
- **Over-processed post-production** — lens flare, heavy vignette, and HDR glow look dated

### Visual Reference Suggestions
- Hero exterior render at golden hour with landscaping
- Interior render of key space with furniture and soft lighting
- Night render showing facade and landscape lighting expression
- Aerial context render showing the building in its neighborhood

### Next Workflow Step
→ **Generate architecture renders** in Image Studio — describe the view, time of day, and mood
→ Or ask about: V-Ray settings, Lumion tips, render composition rules, post-production workflow`;
}

function generateSiteAnalysisResponse(_q: string): string {
  return `## Site Analysis for Architecture

### Concept
Site analysis is the systematic study of a location's physical, environmental, regulatory, and contextual characteristics before design begins. It is the foundation of every good architectural project — the design must respond to the site, not ignore it.

### Site Analysis Framework
| Factor | What to Document |
|---|---|
| **Location & access** | Roads, public transport, pedestrian approaches, vehicular entry points |
| **Topography** | Contour lines, slope direction, cut/fill requirements, drainage patterns |
| **Climate** | Temperature range, rainfall, humidity, wind direction (seasonal), sun path |
| **Orientation** | North direction, solar angles, shadow patterns at different times |
| **Context** | Surrounding buildings (height, use, style), open spaces, landmarks |
| **Vegetation** | Existing trees (species, canopy), protected trees, landscape potential |
| **Soil** | Bearing capacity, water table level, soil type (for foundation design) |
| **Regulations** | Setbacks, FSI, height limit, ground coverage, parking norms, road widening |
| **Views** | Desirable views (hills, water, gardens) and undesirable views (highways, dumps) |
| **Noise** | Traffic noise levels, neighboring activities, acoustic buffer needs |
| **Utilities** | Water main, sewer, electricity, telecom, gas connections |

### Design Best Practices
- **Visit the site at different times** — morning, noon, evening, weekday, weekend
- **Photograph systematically** — panoramic from each corner, street approach, context, sky
- **Map the sun path** — use tools like SunCalc or Autodesk Ecotect for shadow analysis
- **Talk to locals** — they know flooding patterns, wind corridors, noise issues
- **Layer the analysis** — base map + climate overlay + regulation overlay + opportunity/constraint map

### Mistakes to Avoid
- **Designing before visiting the site** — every site has surprises that drawings don't reveal
- **Ignoring the microclimate** — a site next to a lake has different wind patterns than one 500m away
- **Forgetting underground** — water table, rock, existing foundations, buried services
- **Overlooking future development** — neighboring empty plots may become tall buildings

### Visual Reference Suggestions
- Site plan with analysis layers (sun path, wind, access, views)
- Climate data infographic (monthly temperature, rainfall, wind rose)
- Photo documentation sheet with annotated site photographs
- SWOT analysis diagram (Strengths, Weaknesses, Opportunities, Threats)

### Next Workflow Step
→ Share your **site location and dimensions** — I'll help structure the analysis
→ Or ask about: sun path analysis, wind patterns, soil investigation, regulatory checklist`;
}

function generateClimateDesignResponse(_q: string): string {
  return `## Climate-Responsive Architecture

### Concept
Climate-responsive design adapts building form, orientation, materials, and systems to the local climate — reducing energy consumption while maximizing comfort. India has 5 climatic zones, each demanding a distinct architectural approach.

### Indian Climate Zones & Strategies
| Zone | Cities | Key Strategy |
|---|---|---|
| **Hot-Dry** | Jaipur, Jodhpur, Ahmedabad | Thick walls (thermal mass), courtyards, small openings, earth tones |
| **Warm-Humid** | Mumbai, Chennai, Kolkata | Cross-ventilation, large openings, raised floors, reflective roofs |
| **Composite** | Delhi, Lucknow, Nagpur | Adaptive strategy: heavy mass + operable openings + insulation |
| **Temperate** | Bangalore, Pune | Moderate openings, gardens, natural ventilation year-round |
| **Cold** | Shimla, Leh, Srinagar | Compact form, south-facing glazing, insulation, solar heat gain |

### Design Best Practices

**Universal Principles:**
- **Orientation**: Long axis East-West minimizes heat gain on the largest facades
- **Shading**: External shading is 5x more effective than internal blinds
- **Ventilation**: Cross-ventilation needs openings on opposite walls; stack effect needs high-low openings
- **Thermal mass**: Heavy materials (brick, concrete, stone) delay heat transfer by 6-8 hours
- **Roof insulation**: Most critical element — roof receives maximum solar radiation

**Passive Cooling Techniques:**
1. **Courtyard** — Creates microclimate, drives stack ventilation
2. **Jaali / perforated screen** — Filters light, allows airflow, reduces glare
3. **Earth tube cooling** — Underground pipes cool incoming air by 8-12°C
4. **Evaporative cooling** — Water bodies, fountains, wetted surfaces
5. **Green roof** — Reduces roof temperature by 15-20°C in summer
6. **Reflective roof** — White or cool-roof coating reduces heat absorption by 30-40%

### Mistakes to Avoid
- **Glass box architecture in hot climates** — beautiful renders, terrible energy performance
- **Copying Western designs without climate adaptation** — what works in London fails in Chennai
- **Ignoring wind direction** — badly placed openings can create uncomfortable drafts or dead air
- **Over-insulating in warm-humid climates** — you need airflow, not airtight envelopes
- **Neglecting the roof** — it's the largest heat-gaining surface; always insulate and shade

### Visual Reference Suggestions
- Climate-responsive section showing passive strategies
- Comparative diagrams: conventional vs climate-responsive approach
- Wind flow diagram through building section
- Annual temperature/rainfall chart with design response annotations

### Next Workflow Step
→ Share your **project location and climate zone** — I'll suggest specific passive strategies
→ Or ask about: courtyard design, thermal mass calculations, cool roof materials, ventilation sizing`;
}

function generateGeneralResponse(q: string): string {
  return `## Architecture Knowledge

### Concept
${q.length > 20 ? `Thank you for your question about "${q.slice(0, 60)}..."` : "Thank you for your architecture question."}

Architecture is both an art and a science — it integrates design thinking, structural logic, environmental response, material knowledge, and human behavior into built form. Let me provide a structured perspective.

### Key Considerations
- Every design decision should balance **aesthetics**, **function**, and **sustainability**
- Context is crucial — **climate, culture, and site conditions** shape good architecture
- Material selection impacts both **visual character** and **long-term performance**
- Spatial planning should prioritize **human comfort** and **natural light**
- Structure and services must be coordinated from **Day 1**, not retrofitted

### Design Process Overview
| Phase | Activities | Deliverables |
|---|---|---|
| **Pre-design** | Site analysis, brief development, feasibility | Site report, design brief |
| **Concept design** | Parti diagrams, massing, zoning | Concept drawings, 3D massing |
| **Design development** | Plans, sections, elevations, material selection | DD drawings, material board |
| **Construction documents** | Working drawings, specifications, BOQ | CD set, tender documents |
| **Construction** | Site supervision, quality control, coordination | As-built drawings |
| **Post-occupancy** | Performance evaluation, user feedback | POE report |

### Current Industry Trends
- **Biophilic design** — integrating nature into built environments for health and wellbeing
- **Adaptive reuse** — transforming existing structures instead of demolishing
- **Net-zero energy** — buildings that produce as much energy as they consume
- **Modular construction** — factory-built components for speed and quality
- **Computational design** — parametric tools and AI-assisted form-finding
- **Wellness architecture** — WELL certification, circadian lighting, acoustic design

### Practical Tips
1. **Always start with the site** — visit, photograph, measure, document
2. **Sketch before CAD** — hand drawing develops spatial intuition
3. **Design in section** — plans alone never tell the full story
4. **Study precedents** — analyze 3-5 relevant buildings before starting
5. **Coordinate early** — involve structural, MEP, and landscape consultants from concept stage

### Visual Reference Suggestions
- Concept mood board combining spatial, material, and atmospheric references
- Precedent study analysis board with plan diagrams and photos
- Site response diagram showing how the building relates to context

### Next Workflow Step
→ **Tell me more specifically** what you're working on — I can provide deeper, targeted guidance
→ Try asking about: facade design, space planning, materials, Vastu, structural systems, lighting, sustainability, construction details, estimation, or building codes`;
}
