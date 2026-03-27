"""Theme stage for the design orchestration pipeline."""

from __future__ import annotations

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)

DEFAULT_THEME = "modern"
DEFAULT_INTENSITY = "medium"
THEME_VERSION = "v1"
VALID_INTENSITIES = {"low", "medium", "high"}

THEME_RULES: dict[str, dict] = {
    "modern": {
        "style": "modern",
        "color_roles": {"primary": "warm white", "secondary": "taupe", "accent": "charcoal"},
        "soft_accent": "sage grey",
        "materials": ["oak wood", "glass", "matte metal"],
        "lighting": "layered warm ambient lighting",
        "furniture_style": "clean-lined, contemporary",
        "textures": ["smooth wood grain", "matte stone", "soft upholstery"],
        "decor": ["abstract art", "minimal vases", "statement lighting"],
        "signature_decor": "architectural sculptural accent",
        "dos": ["use clean silhouettes", "balance warm neutrals with sharp detailing"],
        "donts": ["avoid clutter", "avoid ornate historic ornamentation"],
        "spatial_preferences": {"open_space": True, "symmetry": "medium", "clutter_level": "low"},
    },
    "contemporary": {
        "style": "contemporary",
        "color_roles": {"primary": "soft grey", "secondary": "off-white", "accent": "deep blue"},
        "soft_accent": "dusty green",
        "materials": ["engineered wood", "glass", "brushed steel"],
        "lighting": "balanced ambient lighting with accent highlights",
        "furniture_style": "sleek, refined, flexible",
        "textures": ["subtle weave fabric", "smooth lacquer", "polished stone"],
        "decor": ["large mirrors", "modern sculpture", "textured rugs"],
        "signature_decor": "overscaled statement art",
        "dos": ["mix crisp surfaces with tactile accents", "keep layouts open and adaptable"],
        "donts": ["avoid overly ornate detailing", "avoid dated theme motifs"],
        "spatial_preferences": {"open_space": True, "symmetry": "medium", "clutter_level": "low"},
    },
    "minimalist": {
        "style": "minimalist",
        "color_roles": {"primary": "white", "secondary": "beige", "accent": "soft grey"},
        "soft_accent": "pale clay",
        "materials": ["light oak", "plaster", "linen"],
        "lighting": "soft diffused natural lighting",
        "furniture_style": "minimal, low-profile, functional",
        "textures": ["natural linen", "smooth plaster", "light wood grain"],
        "decor": ["single statement object", "hidden storage", "subtle ceramics"],
        "signature_decor": "one restrained focal element",
        "dos": ["prioritize negative space", "hide storage wherever possible"],
        "donts": ["avoid visual noise", "avoid decorative excess"],
        "spatial_preferences": {"open_space": True, "symmetry": "high", "clutter_level": "low"},
    },
    "traditional": {
        "style": "traditional",
        "color_roles": {"primary": "cream", "secondary": "walnut brown", "accent": "muted gold"},
        "soft_accent": "sage green",
        "materials": ["dark wood", "upholstery fabric", "brass"],
        "lighting": "warm classic lighting with layered lamps",
        "furniture_style": "ornate, symmetrical, timeless",
        "textures": ["rich fabric", "carved wood", "patterned rugs"],
        "decor": ["framed artwork", "table lamps", "classic drapery"],
        "signature_decor": "heritage-style focal furnishing",
        "dos": ["preserve symmetry", "layer classic materials thoughtfully"],
        "donts": ["avoid stark industrial finishes", "avoid overly sparse styling"],
        "spatial_preferences": {"open_space": False, "symmetry": "high", "clutter_level": "medium"},
    },
    "rustic": {
        "style": "rustic",
        "color_roles": {"primary": "earth brown", "secondary": "warm beige", "accent": "forest green"},
        "soft_accent": "dusty terracotta",
        "materials": ["reclaimed wood", "stone", "wrought iron"],
        "lighting": "warm cozy lighting with lantern-style accents",
        "furniture_style": "hearty, handcrafted, grounded",
        "textures": ["rough wood", "natural stone", "woven textiles"],
        "decor": ["ceramic pottery", "handmade baskets", "vintage accessories"],
        "signature_decor": "weathered artisanal centerpiece",
        "dos": ["favor natural finishes", "show craftsmanship in surfaces"],
        "donts": ["avoid glossy contemporary surfaces", "avoid synthetic-looking materials"],
        "spatial_preferences": {"open_space": False, "symmetry": "medium", "clutter_level": "medium"},
    },
    "industrial": {
        "style": "industrial",
        "color_roles": {"primary": "grey", "secondary": "black", "accent": "metal tones"},
        "soft_accent": "weathered tan",
        "materials": ["steel", "concrete", "exposed brick"],
        "lighting": "warm industrial lighting",
        "furniture_style": "raw, utilitarian",
        "textures": ["brushed metal", "concrete matte", "distressed leather"],
        "decor": ["factory-style pendants", "open shelving", "metal accents"],
        "signature_decor": "exposed structural expression",
        "dos": ["expose structural elements", "use honest unfinished textures"],
        "donts": ["avoid overly soft decorative styling", "avoid delicate ornate furniture"],
        "spatial_preferences": {"open_space": True, "symmetry": "low", "clutter_level": "low"},
    },
    "scandinavian": {
        "style": "scandinavian",
        "color_roles": {"primary": "white", "secondary": "beige", "accent": "light grey"},
        "soft_accent": "muted sage",
        "materials": ["light wood", "linen", "cotton"],
        "lighting": "soft natural lighting",
        "furniture_style": "minimal, functional",
        "textures": ["soft fabric", "wood grain", "woven wool"],
        "decor": ["plants", "simple wall art", "ceramic accents"],
        "signature_decor": "quiet handcrafted accent",
        "dos": ["use natural materials", "maximize natural light"],
        "donts": ["avoid dark colors", "avoid heavy furniture"],
        "spatial_preferences": {"open_space": True, "symmetry": "medium", "clutter_level": "low"},
    },
    "bohemian": {
        "style": "bohemian",
        "color_roles": {"primary": "terracotta", "secondary": "mustard", "accent": "deep teal"},
        "soft_accent": "dusty rose",
        "materials": ["rattan", "cotton", "aged wood"],
        "lighting": "warm ambient lighting with decorative accents",
        "furniture_style": "eclectic, relaxed, layered",
        "textures": ["embroidered fabric", "woven cane", "patterned textiles"],
        "decor": ["plants", "global textiles", "layered art"],
        "signature_decor": "curated collected-object vignette",
        "dos": ["embrace layered textures", "mix artisanal accents thoughtfully"],
        "donts": ["avoid rigid symmetry", "avoid overly sterile styling"],
        "spatial_preferences": {"open_space": False, "symmetry": "low", "clutter_level": "medium"},
    },
    "luxury": {
        "style": "luxury",
        "color_roles": {"primary": "ivory", "secondary": "espresso", "accent": "champagne gold"},
        "soft_accent": "smoked taupe",
        "materials": ["marble", "walnut", "brushed brass"],
        "lighting": "dramatic layered lighting with statement fixtures",
        "furniture_style": "tailored, elegant, premium",
        "textures": ["velvet", "polished stone", "fine wood veneer"],
        "decor": ["sculptural lighting", "statement art", "premium accessories"],
        "signature_decor": "gallery-grade focal piece",
        "dos": ["maintain visual balance", "use premium finishes consistently"],
        "donts": ["avoid low-cost looking finishes", "avoid overcrowding feature elements"],
        "spatial_preferences": {"open_space": True, "symmetry": "high", "clutter_level": "low"},
    },
    "coastal": {
        "style": "coastal",
        "color_roles": {"primary": "soft white", "secondary": "sand", "accent": "sea blue"},
        "soft_accent": "mist grey",
        "materials": ["bleached wood", "cotton", "jute"],
        "lighting": "bright natural lighting with airy ambience",
        "furniture_style": "light, casual, breezy",
        "textures": ["woven jute", "light wood grain", "soft cotton"],
        "decor": ["woven baskets", "glass vases", "subtle nautical art"],
        "signature_decor": "airy natural-fiber focal accent",
        "dos": ["keep palette light", "support breezy circulation and daylight"],
        "donts": ["avoid heavy dark finishes", "avoid overly formal furniture"],
        "spatial_preferences": {"open_space": True, "symmetry": "medium", "clutter_level": "low"},
    },
}


def process(input_data: dict) -> dict:
    """
    Convert normalized intake data into reusable theme rules for downstream engines.

    The returned payload keeps canonical theme keys while preserving legacy aliases
    (`theme`, `palette`, `lighting_style`) used by the current pipeline.
    """
    requested_theme = str(input_data.get("theme", DEFAULT_THEME)).strip().lower()
    requested_intensity = str(input_data.get("style_intensity", DEFAULT_INTENSITY)).strip().lower()
    room_type = str(input_data.get("room_type", "space")).strip().lower()

    logger.info(
        "theme_received",
        extra={
            "theme": requested_theme,
            "style_intensity": requested_intensity,
            "room_type": room_type,
        },
    )

    applied_theme = requested_theme
    if requested_theme not in THEME_RULES:
        applied_theme = DEFAULT_THEME
        logger.warning(
            "fallback_used",
            extra={
                "requested_theme": requested_theme,
                "fallback_theme": DEFAULT_THEME,
                "room_type": room_type,
            },
        )

    applied_intensity = requested_intensity
    if requested_intensity not in VALID_INTENSITIES:
        applied_intensity = DEFAULT_INTENSITY

    theme_rules = deepcopy(THEME_RULES[applied_theme])
    theme_rules = apply_intensity_rules(theme_rules, applied_intensity)
    colors = _build_colors(theme_rules)

    output = {
        "style": theme_rules["style"],
        "style_intensity": applied_intensity,
        "theme_version": THEME_VERSION,
        "colors": colors,
        "color_roles": dict(theme_rules["color_roles"]),
        "materials": list(theme_rules["materials"]),
        "lighting": theme_rules["lighting"],
        "furniture_style": theme_rules["furniture_style"],
        "textures": list(theme_rules["textures"]),
        "decor": list(theme_rules["decor"]),
        "dos": list(theme_rules["dos"]),
        "donts": list(theme_rules["donts"]),
        "spatial_preferences": dict(theme_rules["spatial_preferences"]),
        "room_type": room_type,
        # Backward-compatible aliases for existing downstream engines.
        "theme": theme_rules["style"],
        "palette": list(colors),
        "lighting_style": theme_rules["lighting"],
    }

    logger.info(
        "intensity_applied",
        extra={
            "theme": output["style"],
            "requested_intensity": requested_intensity,
            "applied_intensity": applied_intensity,
            "room_type": room_type,
        },
    )
    logger.info(
        "theme_applied",
        extra={
            "requested_theme": requested_theme,
            "applied_theme": output["style"],
            "style_intensity": applied_intensity,
            "room_type": room_type,
        },
    )
    return output


def apply_intensity_rules(theme_rules: dict, style_intensity: str) -> dict:
    """
    Adjust the expressive strength of the theme without changing the base mapping.
    """
    adjusted = deepcopy(theme_rules)

    if style_intensity == "low":
        soft_accent = adjusted.get("soft_accent")
        if soft_accent:
            adjusted["color_roles"]["accent"] = soft_accent
        adjusted["decor"] = adjusted["decor"][:2]
        adjusted["dos"] = list(adjusted["dos"]) + ["allow subtle crossover accents from adjacent styles"]
        adjusted["donts"] = list(adjusted["donts"])[:1]
        return adjusted

    if style_intensity == "high":
        adjusted["decor"] = list(adjusted["decor"]) + [adjusted["signature_decor"]]
        adjusted["dos"] = list(adjusted["dos"]) + ["keep the palette tightly curated and theme-dominant"]
        adjusted["donts"] = list(adjusted["donts"]) + ["avoid off-theme accent colors or mixed styling cues"]
        return adjusted

    return adjusted


def _build_colors(theme_rules: dict) -> list[str]:
    color_roles = theme_rules["color_roles"]
    colors = [
        color_roles["primary"],
        color_roles["secondary"],
        color_roles["accent"],
    ]
    return list(dict.fromkeys(colors))
