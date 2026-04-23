"""Parametric theme applier — BRD Layer 2A execution arm.

The LLM proposes a DesignGraph; this module refines it so it actually
looks like the chosen theme. Operates on the raw dict (pre-model) so
it can snap colours, clamp dimensions, align materials, and tag
signature moves (e.g. Pedestal plinth vs Mid-Century tapered legs).

Output:
    {
        "graph": <refined dict>,
        "changes": [
            { "path": "...", "rule": "...", "before": ..., "after": ... }, ...
        ],
    }
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy

from app.knowledge import themes

logger = logging.getLogger(__name__)

# Objects whose structural-base matters for Pedestal / Mid-Century differentiation.
_BASE_CARRYING_TYPES = {
    "sofa", "chair", "lounge_chair", "dining_chair", "office_chair",
    "bed", "single_bed", "queen_bed", "king_bed",
    "coffee_table", "dining_table", "desk", "console_table", "side_table",
    "media_console", "tv_unit", "bookshelf", "wardrobe", "cabinet",
}

# Which ergonomic target applies to which object type.
_ERGO_TARGET_MAP: dict[str, str] = {
    "chair": "seat_height_mm",
    "dining_chair": "seat_height_mm",
    "lounge_chair": "seat_height_mm",
    "office_chair": "seat_height_mm",
    "sofa": "seat_height_mm",
    "counter": "counter_height_mm",
    "kitchen_counter": "counter_height_mm",
}


def apply_theme(graph: dict, theme: str) -> dict:
    """Refine a raw LLM-produced design graph toward a theme's parametric rules.

    Non-destructive: caller receives a deep copy of the graph plus a
    changelog for transparency / UI surfacing.
    """
    pack = themes.get(theme)
    if not pack:
        return {"graph": deepcopy(graph), "changes": [], "theme": theme, "applied": False}

    refined = deepcopy(graph)
    changes: list[dict] = []

    _snap_material_names(refined, pack, changes)
    _snap_colours(refined, pack, changes)
    _clamp_ergonomics(refined, pack, changes)
    _tag_signature_moves(refined, pack, changes)
    _ensure_style_metadata(refined, pack, theme, changes)

    logger.info(
        "parametric_theme_applied",
        extra={"theme": theme, "change_count": len(changes)},
    )
    return {
        "graph": refined,
        "changes": changes,
        "theme": theme,
        "theme_display": pack["display_name"],
        "applied": True,
    }


# ── Material palette alignment ───────────────────────────────────────────────

def _snap_material_names(graph: dict, pack: dict, changes: list[dict]) -> None:
    palette = pack.get("material_palette", {})
    primary = [_normalise(m) for m in palette.get("primary", [])]
    secondary = [_normalise(m) for m in palette.get("secondary", [])]
    accent = [_normalise(m) for m in palette.get("accent", [])]
    allowed = primary + secondary + accent
    if not allowed:
        return

    for idx, mat in enumerate(graph.get("materials", [])):
        name = mat.get("name") or ""
        norm = _normalise(name)
        if any(keyword in norm for keyword in allowed):
            continue
        replacement = _suggest_replacement(mat.get("category"), primary + secondary)
        if replacement and replacement != norm:
            changes.append({
                "path": f"materials[{idx}].name",
                "rule": "theme_material_palette",
                "before": name,
                "after": replacement,
            })
            mat["name"] = replacement.replace("_", " ").title()


def _suggest_replacement(category: str | None, candidates: list[str]) -> str | None:
    """Pick the first candidate whose bucket fits the material category."""
    if not candidates:
        return None
    cat = (category or "").lower()
    bucket_hints = {
        "wood": {"walnut", "oak", "teak", "rosewood", "rubberwood", "plywood"},
        "metal": {"brass", "steel", "aluminium", "aluminum", "iron", "bronze"},
        "stone": {"travertine", "marble", "granite", "limestone", "slate"},
        "fabric": {"wool", "linen", "cotton", "bouclé", "boucle"},
    }.get(cat)
    if bucket_hints:
        for c in candidates:
            if any(hint in c for hint in bucket_hints):
                return c
    return candidates[0]


# ── Colour palette alignment ────────────────────────────────────────────────

def _snap_colours(graph: dict, pack: dict, changes: list[dict]) -> None:
    palette_hex = [c for c in pack.get("colour_palette", []) if _is_hex(c)]
    if not palette_hex:
        return
    palette_rgb = [_hex_to_rgb(c) for c in palette_hex]
    threshold = 80.0  # only snap clearly drifting colours

    for idx, obj in enumerate(graph.get("objects", [])):
        col = obj.get("color")
        if not _is_hex(col):
            continue
        target, dist = _closest_palette_colour(col, palette_hex, palette_rgb)
        if target and dist > threshold and target.lower() != col.lower():
            changes.append({
                "path": f"objects[{idx}].color",
                "rule": "theme_colour_palette",
                "before": col,
                "after": target,
                "distance": round(dist, 1),
            })
            obj["color"] = target

    for idx, mat in enumerate(graph.get("materials", [])):
        col = mat.get("color")
        if not _is_hex(col):
            continue
        target, dist = _closest_palette_colour(col, palette_hex, palette_rgb)
        if target and dist > threshold and target.lower() != col.lower():
            changes.append({
                "path": f"materials[{idx}].color",
                "rule": "theme_colour_palette",
                "before": col,
                "after": target,
                "distance": round(dist, 1),
            })
            mat["color"] = target


def _closest_palette_colour(hex_value: str, palette_hex: list[str], palette_rgb: list[tuple[int, int, int]]):
    target_rgb = _hex_to_rgb(hex_value)
    best_idx = 0
    best_dist = float("inf")
    for i, rgb in enumerate(palette_rgb):
        dist = _rgb_distance(target_rgb, rgb)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return palette_hex[best_idx], best_dist


# ── Ergonomic clamping ──────────────────────────────────────────────────────

def _clamp_ergonomics(graph: dict, pack: dict, changes: list[dict]) -> None:
    targets = pack.get("ergonomic_targets", {})
    if not targets:
        return

    for idx, obj in enumerate(graph.get("objects", [])):
        otype = (obj.get("type") or "").lower()
        target_key = _ERGO_TARGET_MAP.get(otype)
        if not target_key:
            continue
        rng = targets.get(target_key)
        if not rng or not isinstance(rng, tuple) or len(rng) != 2:
            continue
        lo_mm, hi_mm = rng
        dims = obj.get("dimensions") or {}
        height = dims.get("height")
        if height is None:
            continue
        height_mm = _to_mm(height)
        if height_mm is None:
            continue
        if height_mm < lo_mm or height_mm > hi_mm:
            clamped_mm = max(lo_mm, min(hi_mm, height_mm))
            new_value = clamped_mm / 1000.0 if height < 20 else clamped_mm
            changes.append({
                "path": f"objects[{idx}].dimensions.height",
                "rule": f"theme_ergonomic_clamp:{target_key}",
                "before": height,
                "after": round(new_value, 3),
                "range_mm": [lo_mm, hi_mm],
            })
            dims["height"] = round(new_value, 3)


# ── Signature move tagging ──────────────────────────────────────────────────

def _tag_signature_moves(graph: dict, pack: dict, changes: list[dict]) -> None:
    signatures = pack.get("signature_moves", [])
    style_name = pack["display_name"].lower()
    if not signatures:
        return

    base_tag = None
    if "pedestal" in style_name or "plinth" in style_name:
        base_tag = "plinth"
    elif "mid" in style_name and "century" in style_name:
        base_tag = "tapered_legs"
    elif "modern" in style_name:
        base_tag = "cantilever_or_slim_legs"

    if not base_tag:
        return

    for idx, obj in enumerate(graph.get("objects", [])):
        otype = (obj.get("type") or "").lower()
        if otype not in _BASE_CARRYING_TYPES:
            continue
        meta = obj.setdefault("metadata", {})
        existing = meta.get("base_type")
        if existing == base_tag:
            continue
        meta["base_type"] = base_tag
        meta["signature_moves"] = signatures
        changes.append({
            "path": f"objects[{idx}].metadata.base_type",
            "rule": "theme_signature_move",
            "before": existing,
            "after": base_tag,
        })


# ── Style metadata ──────────────────────────────────────────────────────────

def _ensure_style_metadata(graph: dict, pack: dict, theme_key: str, changes: list[dict]) -> None:
    style = graph.setdefault("style", {})
    before = style.get("primary")
    canonical = pack["display_name"]
    if before != canonical:
        style["primary"] = canonical
        changes.append({
            "path": "style.primary",
            "rule": "theme_canonical_name",
            "before": before,
            "after": canonical,
        })

    # Append theme palette / material hints for downstream engines.
    style["theme_key"] = theme_key
    style["colour_palette"] = pack.get("colour_palette", [])
    style["material_palette"] = pack.get("material_palette", {})


# ── helpers ─────────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def _is_hex(value) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _normalise(name: str) -> str:
    return (name or "").strip().lower().replace("-", " ").replace("_", " ")


def _to_mm(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v * 1000.0 if v < 20 else v
