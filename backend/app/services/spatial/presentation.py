"""Presentation render — the styling / mood system that turns the faithful
model into hero-image architectural *photography* (the "storefront").

Deliberately the opposite of ``finish.build_finish_prompt`` (which locks the
geometry and forbids atmosphere): a PRESENTATION prompt ADDS site, light,
materials and lifestyle styling — the editorial look a client or manager reacts
to. Geometry still comes from the kernel render underneath, and with a Replicate
token the finish is depth-locked by ControlNet so the beauty is your ACTUAL
building. Without a token the atmospheric img2img finish runs — a mood/hero shot
that reads as photography (it may drift slightly; that's the interim trade-off).

The knobs below are tuned to the warm, natural, Mediterranean-resort editorial
language most hospitality references share. Every field auto-derives a tasteful
default from the design and is overridable per request.
"""
from __future__ import annotations

# ── the look knobs ────────────────────────────────────────────────────────────

LIGHT = {
    "golden_hour": "warm golden-hour sunlight, long soft shadows, a low glowing sun and luminous sky",
    "morning": "soft clear morning light, gentle long shadows, a fresh airy atmosphere",
    "midday": "bright midday sun with crisp dappled shade cast through pergola and foliage",
    "blue_hour": "blue-hour dusk — warm interior and lamp glow against a deep cool sky",
    "overcast": "soft overcast diffuse light, even and muted, no harsh shadows",
}

SETTING = {
    "mediterranean": "on a sun-drenched Mediterranean hillside — olive and cypress trees, dry-stone terraces, native drought planting, a hazy sea or valley beyond",
    "coastal": "on a coastal cliff above turquoise water, weathered rocks and open sea beyond",
    "desert": "in an arid desert landscape — sculptural boulders, agave, yucca and palms under a vast clear sky",
    "quarry": "built into a dramatic rocky quarry with a still turquoise water pool below and pale stone cliffs around",
    "forest": "nestled among pines and lush greenery with dappled forest light",
    "garden": "in a lush landscaped garden — mature trees, ornamental grasses and a manicured lawn",
    "urban": "in a refined urban setting with mature street trees and a quiet paved forecourt",
    "none": "in a simple, uncluttered natural setting that keeps all focus on the architecture",
}

PALETTE = {
    "natural_warm": "warm natural palette — cream lime-plaster, honey timber, travertine and stone, woven reed, matte-black accents",
    "coastal_light": "light coastal palette — whitewashed walls, pale wood, linen and bleached stone",
    "mineral": "earthy mineral palette — raw concrete, sandstone, terracotta and oxidised metal",
    "monochrome_stone": "quiet monochrome stone palette — limestone, plaster and muted greys and taupes",
}

STYLING = {
    "styled": ("styled like a luxury boutique-hotel editorial shoot: designer furniture, layered textiles "
               "and cushions, potted plants and greenery, ceramics and a few subtle props, warm ambient lamps"),
    "minimal": "sparse, considered styling — a few refined furniture pieces and one or two plants, uncluttered",
    "none": "no added props — clean and purely architectural",
}

# Region hint (graph.region / climate) → a fitting outdoor setting. Anything
# unmatched falls back to the tasteful Mediterranean default the references use.
_REGION_SETTING = {
    "coast": "coastal", "sea": "coastal", "island": "coastal", "beach": "coastal",
    "desert": "desert", "arid": "desert", "gulf": "desert", "uae": "desert", "rajasthan": "desert",
    "hill": "mediterranean", "mediterranean": "mediterranean", "greece": "mediterranean",
    "italy": "mediterranean", "spain": "mediterranean", "forest": "forest", "alpine": "forest",
    "urban": "urban", "city": "urban", "metro": "urban",
}


def _design_materials(graph: dict) -> str:
    """Real material names only — an object's ``material`` (never its type-name,
    so we don't list 'Sofa, Coffee Table' as materials) plus the materials list."""
    seen: set[str] = set()
    mats: list[str] = []

    def add(name) -> None:
        if isinstance(name, str) and name.strip() and name.lower() not in seen:
            seen.add(name.lower())
            mats.append(name.strip())

    for o in graph.get("objects") or []:
        if isinstance(o, dict):
            add(o.get("material"))
    for m in graph.get("materials") or []:
        if isinstance(m, dict):
            add(m.get("name") or m.get("material"))
    return ", ".join(mats[:10]) or "lime plaster, timber, natural stone, glass"


def _auto_mood(graph: dict) -> dict:
    """A tasteful default mood derived from the design — warm natural editorial,
    golden hour, styled. Setting follows the region/climate when the graph
    carries one, else the Mediterranean-resort default the references share."""
    region = ""
    for k in ("region", "climate", "location", "site"):
        v = graph.get(k)
        if isinstance(v, str) and v.strip():
            region = v.lower()
            break
    setting = "mediterranean"
    for kw, s in _REGION_SETTING.items():
        if kw in region:
            setting = s
            break
    return {
        "setting": setting,
        "light": "golden_hour",
        "palette": "natural_warm",
        "styling": "styled",
        "people": False,
        "mood_words": "serene, luxurious, editorial, warm and inviting",
    }


def build_presentation_prompt(graph: dict, *, kind: str = "exterior", mood: dict | None = None) -> str:
    """Rich, atmospheric photography prompt for a hero/presentation render.

    ``mood`` overrides any of: setting, light, palette, styling, people (bool),
    mood_words. Omitted fields auto-derive from the design.
    """
    m = {**_auto_mood(graph), **{k: v for k, v in (mood or {}).items() if v is not None}}
    materials = _design_materials(graph)
    light = LIGHT.get(str(m.get("light")), LIGHT["golden_hour"])
    palette = PALETTE.get(str(m.get("palette")), PALETTE["natural_warm"])
    styling = STYLING.get(str(m.get("styling")), STYLING["styled"])
    people = ("a few people relaxing at natural human scale to give life and scale, "
              if m.get("people") else "")
    mood_words = str(m.get("mood_words") or "serene, editorial, warm")

    if kind == "product":
        return (
            f"Editorial lifestyle product photograph of this single piece in a beautifully styled corner. "
            f"{light}. Materials: {materials}. {palette}. Photoreal, magazine-quality, shallow depth of field, "
            f"soft studio-daylight. Keep the object's exact shape and proportions as in the model — render only "
            f"its materials, light and a tasteful styled backdrop. Show only this one piece."
        )

    if kind == "interior":
        return (
            f"Editorial interior architectural photography — a natural eye-level view through a wide architectural lens. "
            f"{light} pouring through the openings. Materials: {materials}. {palette}. Furnished and {styling}. {people}"
            f"Mood: {mood_words}. Photoreal, atmospheric, cinematic, shallow depth of field, professional. "
            f"Keep the room's shape, wall positions and the FURNITURE LAYOUT exactly as in the model — render each "
            f"block as the real, beautifully styled piece it represents (never a plain box). Do not add or remove "
            f"rooms or walls, and do not add text, labels or plan lines."
        )

    # exterior — the default; this is the language the hospitality references share
    setting = SETTING.get(str(m.get("setting")), SETTING["mediterranean"])
    return (
        f"Editorial architectural photography — an eye-level three-quarter hero view through a wide architectural lens "
        f"of this building {setting}. {light}. Natural materials: {materials}. {palette}. {styling}. {people}"
        f"Mood: {mood_words}, luxury-resort atmosphere with dappled light and shade. Photoreal, cinematic, atmospheric, "
        f"shallow depth of field, high detail, professional. Keep the building's massing, footprint and proportions "
        f"as in the model — render it beautifully within its landscape. Do not add extra floors or change the "
        f"building's shape, and do not add text, labels or diagram lines."
    )
