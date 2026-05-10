"""Graph → English description for image generation.

The image-generation provider (Gemini 2.0 Flash) sees only text. To make
edits like "move the table 30cm right" actually surface in the next
render, the prompt has to carry the geometry — not just the user's
typed brief. This module walks a design graph and produces a compact
paragraph the image model can condition on:

    Spaces:
      • Living room: 4.5m × 3.8m × 2.7m
    Objects:
      • Dining table (walnut · 1.8m × 0.9m × 0.76m, at 3.20m, 2.00m, 0.00m)
      • Chair (walnut · 0.5m × 0.5m × 0.9m, at 3.20m, 1.20m, 0.00m)
      • Pendant lamp (brass · 0.4m diameter sphere, at 3.20m, 2.00m, 2.10m)
    Lighting: pendant (#FFE6B3), ambient (#FFFFFF)

The description is best-effort and resilient: missing fields are
skipped silently, the object list is truncated to keep prompts inside
Gemini's budget, and an empty graph yields an empty string (the caller
falls back to the user's prompt alone).

This is the structured-text path to graph-driven rendering. A later
refinement could rasterize a top-down plan from the graph and pass it
as a multimodal `inlineData` reference image — strictly stronger but
substantially more moving parts. For now, structured text gets the
edit-loop honest enough that material + general-geometry edits land.
"""

from __future__ import annotations

from typing import Any

# Hard cap on how many objects we describe. Beyond this Gemini's
# attention drops off and prompts get expensive. Architects rarely
# need more than ~30 named objects in a single render.
_MAX_OBJECTS = 30
_MAX_SPACES = 3
_MAX_LIGHTS = 5


def describe_graph_for_render(graph_data: Any) -> str:
    """Produce a compact English description of a design graph.

    Returns an empty string when the graph is missing or yields no
    visually-relevant content. Callers should treat the empty string
    as "no extra context to add" and not append it.
    """
    if not isinstance(graph_data, dict):
        return ""

    lines: list[str] = []

    # ── Spaces — give the room envelope first so subsequent objects
    # have a frame of reference. Uses the first few spaces only.
    spaces_block = _describe_spaces(graph_data.get("spaces"))
    if spaces_block:
        lines.append(spaces_block)

    # ── Objects — the load-bearing block. This is what changes when
    # the architect edits, so it's where the render benefit shows up.
    objects_block = _describe_objects(graph_data.get("objects"))
    if objects_block:
        lines.append(objects_block)

    # ── Lighting — top-level lighting nodes (excluded from objects).
    lighting_block = _describe_lighting(graph_data.get("lighting"))
    if lighting_block:
        lines.append(lighting_block)

    return "\n".join(lines).strip()


# ── Section helpers ────────────────────────────────────────────────────


def _describe_spaces(spaces: Any) -> str:
    if not isinstance(spaces, list) or not spaces:
        return ""
    rows: list[str] = []
    for s in spaces[:_MAX_SPACES]:
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or s.get("room_type") or "space").replace("_", " ")
        d = s.get("dimensions") or {}
        l = _num(d.get("length"))
        w = _num(d.get("width"))
        h = _num(d.get("height"))
        dim_str = " × ".join(f"{v}m" for v in (l, w, h) if v is not None)
        rows.append(f"  • {name}{f': {dim_str}' if dim_str else ''}")
    if not rows:
        return ""
    return "Spaces:\n" + "\n".join(rows)


def _describe_objects(objects: Any) -> str:
    if not isinstance(objects, list) or not objects:
        return ""
    rows: list[str] = []
    for obj in objects[:_MAX_OBJECTS]:
        line = _describe_object(obj)
        if line:
            rows.append(f"  • {line}")
    overflow = max(0, len(objects) - _MAX_OBJECTS)
    if overflow:
        rows.append(f"  • …and {overflow} more")
    if not rows:
        return ""
    return "Objects:\n" + "\n".join(rows)


def _describe_object(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    name = (obj.get("name") or "").strip()
    obj_type = (obj.get("type") or "object").strip()
    label = name or obj_type.replace("_", " ")

    parts = [label]

    # Material + color in a single parenthetical so the line stays
    # readable even when both are present.
    material = (obj.get("material") or "").strip()
    color = (obj.get("color") or "").strip()
    if material or color:
        # Skip color when it's already implied by the material name
        # (e.g. "walnut" already conveys a brown). Heuristic: if the
        # material string is multi-letter alpha, drop a redundant hex.
        keep_color = bool(color) and (
            not material or color.lower() not in material.lower()
        )
        m_parts = [p for p in [material, color if keep_color else None] if p]
        if m_parts:
            parts.append(f"({', '.join(m_parts)})")

    # Dimensions (length × width × height in metres)
    dims = obj.get("dimensions") or {}
    if isinstance(dims, dict):
        l = _num(dims.get("length"))
        w = _num(dims.get("width"))
        h = _num(dims.get("height"))
        d_parts = [f"{v}m" for v in (l, w, h) if v is not None]
        if d_parts:
            parts.append(" × ".join(d_parts))

    # Position — coarse coordinates in metres so Gemini can place the
    # object relative to the room envelope. We don't try to translate
    # to "north wall" / "centred" because the room shape isn't
    # guaranteed to be rectilinear or origin-aligned.
    pos = obj.get("position") or {}
    if isinstance(pos, dict):
        x = _num(pos.get("x"))
        y = _num(pos.get("y"))
        z = _num(pos.get("z"))
        if any(v is not None for v in (x, y, z)):
            x_s = _fmt_axis(x)
            y_s = _fmt_axis(y)
            z_s = _fmt_axis(z)
            parts.append(f"at ({x_s}, {y_s}, {z_s})m")

    return " · ".join(parts)


def _describe_lighting(lights: Any) -> str:
    if not isinstance(lights, list) or not lights:
        return ""
    rows: list[str] = []
    for light in lights[:_MAX_LIGHTS]:
        if not isinstance(light, dict):
            continue
        ltype = (light.get("type") or "light").replace("_", " ")
        intensity = _num(light.get("intensity"))
        color = (light.get("color") or "").strip()
        bits = [ltype]
        if intensity is not None:
            bits.append(f"intensity {intensity}")
        if color:
            bits.append(color)
        rows.append(" ".join(bits))
    if not rows:
        return ""
    return "Lighting: " + "; ".join(rows)


# ── Number formatting ──────────────────────────────────────────────────


def _num(v: Any) -> float | None:
    """Coerce to float, returning None on missing / non-numeric input.
    Strips zeros that would just be noise — exact 0 is preserved (it's
    a real position, distinct from "missing"), but None / non-numbers
    drop out of the output."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_axis(v: float | None) -> str:
    """Render a single axis value: '0' for None, otherwise 2-decimal."""
    if v is None:
        return "0"
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"
