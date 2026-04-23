"""Parametric theme rule packs (BRD Layer 2A).

Each theme is a structured rule set: proportions, material palette,
hardware, colour, ergonomic targets, signature moves, do / don't lists.
These are consumed at generation time to shape the LLM prompt and at
validation time to check output alignment.

The existing services/theme_engine.py keeps surface-level theme metadata
for the pipeline stage; this module holds the deeper parametric rules.
"""

from __future__ import annotations

from copy import deepcopy

# Primary BRD themes.
THEMES: dict[str, dict] = {
    "pedestal": {
        "display_name": "Pedestal",
        "era": "2020s",
        "origin": "KATHA studio signature — plinth / pedestal-driven forms",
        "proportions": {
            "base_to_body_ratio": (0.12, 0.22),   # plinth height / object height
            "overhang_mm": (20, 60),               # body oversail past base
            "verticality_preference": "balanced",
            "silhouette": "elevated-body-on-distinct-plinth",
        },
        "material_palette": {
            "primary": ["walnut", "oak", "travertine"],
            "secondary": ["brushed brass", "powder-coat steel"],
            "upholstery": ["wool bouclé", "grade A leather"],
            "accent": ["burnished bronze"],
        },
        "hardware": {
            "style": "hidden or plinth-integrated",
            "material": "brushed brass, burnished bronze",
            "finish": "matte",
        },
        "colour_palette": ["#2f2a25", "#c9b79a", "#d7c3a6", "#5a4632", "#8a6a3b"],
        "ergonomic_targets": {
            "seat_height_mm": (380, 430),         # slightly lower, lounge-leaning
            "counter_height_mm": (880, 920),
        },
        "signature_moves": [
            "monolithic plinth with lighter body above",
            "shadow-gap reveal between base and body",
            "brass inlay on plinth edge",
        ],
        "dos": [
            "emphasise the split between base and object body",
            "keep the plinth material heavier / darker than the body",
            "use shadow gaps to float the body visually",
        ],
        "donts": [
            "avoid legs or tapered feet (the plinth IS the base)",
            "avoid continuous-material monoliths",
            "avoid ornate trim",
        ],
    },
    "mid_century_modern": {
        "display_name": "Mid-Century Modern",
        "era": "1945-1965 revival",
        "proportions": {
            "leg_taper_ratio": (0.6, 0.8),        # top/bottom leg diameter
            "leg_angle_deg": (5, 12),              # outward splay
            "overall_profile": "low-slung",
            "seat_height_mm": (380, 430),
        },
        "material_palette": {
            "primary": ["walnut", "teak"],
            "secondary": ["oak", "rosewood (vintage)"],
            "upholstery": ["wool", "vintage leather"],
            "accent": ["brass"],
        },
        "hardware": {
            "style": "minimal visible, brass accents",
            "material": "solid brass",
            "finish": "polished or brushed",
        },
        "colour_palette": ["#6b4a2b", "#c19a6b", "#2a4d3a", "#c23b22", "#e8d9b0"],
        "ergonomic_targets": {
            "seat_height_mm": (380, 430),
            "backrest_angle_deg": (100, 108),
            "lounge_depth_mm": (500, 600),
        },
        "signature_moves": [
            "tapered splayed legs",
            "organic / kidney curves",
            "exposed wood frame with upholstered cushion",
        ],
        "dos": [
            "use warm woods (walnut / teak) as primary",
            "add brass accents sparingly",
            "keep silhouette low and horizontal",
        ],
        "donts": [
            "avoid heavy blocky legs",
            "avoid cold greys as primary palette",
            "avoid ornate Victorian detailing",
        ],
    },
    "contemporary": {
        "display_name": "Contemporary",
        "era": "current",
        "proportions": {
            "form": "clean-line cubic or cylindrical",
            "leg_style": "straight or plinth",
            "seat_height_mm": (420, 460),
        },
        "material_palette": {
            "primary": ["teak", "engineered veneer", "lacquered MDF"],
            "secondary": ["brushed steel", "glass"],
            "upholstery": ["performance fabric", "leather"],
        },
        "hardware": {
            "style": "minimal, integrated",
            "material": "stainless steel, matched finish",
            "finish": "matte",
        },
        "colour_palette": ["#ffffff", "#d9d4cb", "#222322", "#b84a2b", "#2f5f7c"],
        "ergonomic_targets": {
            "seat_height_mm": (420, 460),
            "counter_height_mm": (850, 900),
        },
        "signature_moves": [
            "flush integrated handles",
            "bold accent colour on a neutral field",
            "hidden / tucked storage",
        ],
        "dos": [
            "prioritise clean geometry",
            "use one bold accent colour per composition",
            "keep surfaces flush and continuous",
        ],
        "donts": [
            "avoid distressed finishes",
            "avoid ornamental turning or carving",
        ],
    },
    "modern": {
        "display_name": "Modern",
        "era": "1920s-1950s international style",
        "proportions": {
            "form": "balanced modular",
            "leg_style": "slim straight or cantilever",
            "seat_height_mm": (420, 460),
        },
        "material_palette": {
            "primary": ["oak", "steel", "glass"],
            "secondary": ["leather", "felt"],
        },
        "hardware": {
            "style": "industrial honest",
            "material": "blackened steel, chrome",
            "finish": "visible fasteners OK",
        },
        "colour_palette": ["#e8e4db", "#3b3b3b", "#8a8a8a", "#b5895f"],
        "ergonomic_targets": {
            "seat_height_mm": (420, 460),
        },
        "signature_moves": [
            "cantilever frames",
            "monochromatic palette with warm wood",
            "modular / stackable pieces",
        ],
        "dos": [
            "let structure express itself",
            "use modular repetition",
        ],
        "donts": [
            "avoid ornamental mouldings",
            "avoid glossy maximalist accents",
        ],
    },
    "custom": {
        "display_name": "Custom",
        "proportions": {"form": "user-defined"},
        "material_palette": {"primary": [], "secondary": []},
        "hardware": {"style": "user-defined"},
        "colour_palette": [],
        "ergonomic_targets": {},
        "signature_moves": [],
        "dos": ["follow the user's brief exactly"],
        "donts": [],
    },
}

# Aliases — map loose / legacy strings to canonical theme keys.
_ALIASES: dict[str, str] = {
    "midcentury": "mid_century_modern",
    "mid-century": "mid_century_modern",
    "mid century": "mid_century_modern",
    "mcm": "mid_century_modern",
    "theme_v": "pedestal",
    "theme v": "pedestal",
    "plinth": "pedestal",
}


def get(name: str) -> dict | None:
    """Fetch a theme rule pack by name (case / alias tolerant)."""
    if not name:
        return None
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    key = _ALIASES.get(key, key)
    pack = THEMES.get(key)
    return deepcopy(pack) if pack else None


def list_names() -> list[str]:
    return list(THEMES.keys())


def describe_for_prompt(name: str) -> str:
    """Render a compact multi-line description for injection into LLM prompts."""
    pack = get(name)
    if not pack:
        return f"(No parametric rules found for theme '{name}'.)"
    lines = [f"Theme: {pack['display_name']}"]
    mats = pack["material_palette"]
    if mats.get("primary"):
        lines.append(f"- Primary materials: {', '.join(mats['primary'])}")
    if mats.get("secondary"):
        lines.append(f"- Secondary materials: {', '.join(mats['secondary'])}")
    if mats.get("upholstery"):
        lines.append(f"- Upholstery: {', '.join(mats['upholstery'])}")
    if pack.get("colour_palette"):
        lines.append(f"- Colour palette: {', '.join(pack['colour_palette'])}")
    hw = pack.get("hardware", {})
    if hw:
        lines.append(f"- Hardware: {hw.get('style','')} ({hw.get('material','')}, {hw.get('finish','')})")
    ergo = pack.get("ergonomic_targets", {})
    if ergo:
        ergo_bits = [f"{k}={v}" for k, v in ergo.items()]
        lines.append(f"- Ergonomic targets: {', '.join(ergo_bits)}")
    if pack.get("signature_moves"):
        lines.append(f"- Signature moves: {'; '.join(pack['signature_moves'])}")
    if pack.get("dos"):
        lines.append(f"- Do: {'; '.join(pack['dos'])}")
    if pack.get("donts"):
        lines.append(f"- Don't: {'; '.join(pack['donts'])}")
    return "\n".join(lines)
