"""Graph → reference image for grounded rendering.

The photoreal render must be a *function of the design graph*, not an
independent text-to-image guess. This module rasterises the graph's
geometry into a clean top-down plan image that conditions the image
model (Gemini) on the **actual** layout: the room envelope plus every
object's footprint, placed and sized straight from the graph and
coloured by its material.

Why this exists
---------------
The prior render path appended a text description of the geometry
("Desk · 1.5m × 0.8m at (1.50, 0.50, 0)m") to the image prompt. Image
models can't consume coordinates spatially — they render the *numbers*
as visible dimension lines, so renders came back with garbled
measurement text scrawled across them, and the layout ignored what the
architect actually placed.

A reference image fixes both failure modes at once:
  • The layout is carried by pixels, not prose — so it's faithful and
    stable across re-renders.
  • The prompt carries only qualitative signal (style, materials,
    mood) — so there are no numerals for the model to hallucinate into
    the frame. **The reference itself is deliberately text-free.**

Projection
----------
We reuse :func:`app.services.object_bboxes.compute_object_bboxes`, the
same deterministic top-down (plan) projection the click-to-edit overlay
trusts, so this stays consistent with the rest of the system and never
re-invents the graph's coordinate convention.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from PIL import Image, ImageDraw

from app.services.object_bboxes import compute_object_bboxes

logger = logging.getLogger(__name__)

# Aspect-ratio slug → (width, height) in px. Mirrors the ratios offered
# in the design workspace so the reference (and therefore the render)
# comes out in the shape the architect asked for.
_RATIO_SIZES: dict[str, tuple[int, int]] = {
    "16:9": (1024, 576),
    "4:3": (1024, 768),
    "1:1": (1024, 1024),
    "3:4": (768, 1024),
    "9:16": (576, 1024),
}
_DEFAULT_SIZE = (1024, 576)

# Palette for the plan itself (not the design). Deliberately FILL-ONLY,
# no hard outlines: an image-editing model traces crisp black strokes
# straight into the render as ghost rectangles. Soft colour boundaries
# read as "zones to interpret" instead of "lines to keep", so the room
# edge and every footprint are carried by fill contrast alone.
#
#   • surround  — a warm mid-grey "outside the room"
#   • floor     — a light plane; its edge against the surround is the room
#   • objects   — their true material colour, filled, no stroke
_SURROUND = (198, 194, 188)
_FLOOR = (243, 242, 238)
_FALLBACK_OBJ = (150, 150, 150)


def size_for_ratio(ratio: str | None) -> tuple[int, int]:
    """Resolve an aspect-ratio slug to a pixel canvas size."""
    if not ratio:
        return _DEFAULT_SIZE
    return _RATIO_SIZES.get(ratio.strip(), _DEFAULT_SIZE)


def build_reference_image(
    graph_data: Any,
    *,
    ratio: str | None = None,
    size: tuple[int, int] | None = None,
) -> bytes | None:
    """Render the graph as a clean top-down plan PNG for image conditioning.

    Returns PNG bytes, or ``None`` when the graph has no usable room or
    objects (the caller then falls back to a prompt-only render).

    The image is intentionally minimal — a bordered room floor and one
    colour-filled footprint per object. No labels, dimensions, or text:
    those are exactly what the render must not inherit.
    """
    boxes = compute_object_bboxes(graph_data)
    if not boxes:
        return None

    width, height = size or size_for_ratio(ratio)

    # Colour lookup by object id — compute_object_bboxes doesn't carry
    # colour, so pull it from the graph objects directly.
    colours: dict[str, tuple[int, int, int]] = {}
    for obj in graph_data.get("objects", []) or []:
        if isinstance(obj, dict) and obj.get("id"):
            colours[obj["id"]] = _parse_hex(obj.get("color"))

    img = Image.new("RGB", (width, height), _SURROUND)
    draw = ImageDraw.Draw(img, "RGBA")

    # Room floor — a light plane inset from the canvas edge. No outline:
    # the fill contrast against the surround defines the room, and there's
    # no stroke for the model to reproduce.
    margin = round(min(width, height) * 0.07)
    rx0, ry0 = margin, margin
    rx1, ry1 = width - margin, height - margin
    draw.rectangle([rx0, ry0, rx1, ry1], fill=_FLOOR)
    room_w, room_h = rx1 - rx0, ry1 - ry0

    # Draw largest footprints first so small objects land on top and stay
    # visible (a rug shouldn't bury the chair sitting on it). Fill-only,
    # fully opaque — the material colour is the whole signal.
    for box in sorted(boxes, key=lambda b: b["w"] * b["h"], reverse=True):
        px0 = rx0 + box["x"] * room_w
        py0 = ry0 + box["y"] * room_h
        px1 = px0 + box["w"] * room_w
        py1 = py0 + box["h"] * room_h
        colour = colours.get(box["id"], _FALLBACK_OBJ)
        draw.rectangle([px0, py0, px1, py1], fill=(*colour, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def describe_graph_materials(graph_data: Any, *, max_objects: int = 16) -> str:
    """A one-line, number-free summary of objects and their materials.

    Feeds the render prompt qualitative grounding — e.g.
    ``"Standing Desk (oak wood), Ergonomic Task Chair (leather)"`` — so
    the model renders the right materials without any dimensions or
    coordinates it could turn into on-image text. Material *slugs*
    (``mat_floor_oak``) are resolved to readable names via the graph's
    materials table, and dropped if unresolvable.
    """
    if not isinstance(graph_data, dict):
        return ""

    mat_names: dict[str, str] = {}
    for m in graph_data.get("materials") or []:
        if isinstance(m, dict) and m.get("id"):
            mat_names[m["id"]] = (m.get("name") or "").strip()

    parts: list[str] = []
    for obj in (graph_data.get("objects") or [])[:max_objects]:
        if not isinstance(obj, dict):
            continue
        name = (obj.get("name") or "").strip() or (
            obj.get("type") or ""
        ).replace("_", " ").strip()
        if not name:
            continue
        material = (obj.get("material") or "").strip()
        material = mat_names.get(material, material)
        if material.startswith("mat_"):  # unresolved slug — drop it
            material = ""
        if material and material.lower() not in name.lower():
            parts.append(f"{name} ({material})")
        else:
            parts.append(name)
    return ", ".join(parts)


def _parse_hex(value: Any) -> tuple[int, int, int]:
    """Parse a ``#rrggbb`` / ``#rgb`` colour to an RGB tuple.

    Falls back to a neutral grey for missing or malformed values so a
    bad colour never breaks the reference.
    """
    if not isinstance(value, str):
        return _FALLBACK_OBJ
    s = value.strip().lstrip("#")
    try:
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        pass
    return _FALLBACK_OBJ
