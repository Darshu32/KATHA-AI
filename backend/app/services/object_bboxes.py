"""Approximate object hotspots for click-to-edit on the rendered image.

Honest tradeoff
---------------
Gemini's photoreal renders pick their own camera each time — there's no
reliable way to extract pixel-accurate bounding boxes from the model's
output. Instead, this module computes **logical** bounding boxes from
the design graph using a deterministic top-down (plan-view) projection.

The architect interacts with them like this:
  • Hover the rendered image → invisible hotspot under the cursor
    highlights with the object's name.
  • Click → selects the object → opens the edit popover (same flow as
    the right-panel list, just reachable from the image directly).

Because the projection is logical-not-photographic, hotspots don't
always sit *on* the visually-rendered object. They sit on the
"footprint" position the graph thinks the object occupies. For a
prototype that's the right tradeoff: hotspots are deterministic,
versioning-stable, and never lie about what got clicked.

Projection model
----------------
Room convention from the drawing engine:
  x ∈ [0, length] — left-right
  y ∈ [0, width]  — depth (front-to-back; near camera = small y)
  z ∈ [0, height] — floor-to-ceiling

Top-down ("plan") projection:
  image_x = object_x / room_length
  image_y = object_y / room_width
  image_w = object_length / room_length
  image_h = object_width / room_width

When dimensions are missing, the object gets a minimum-size hotspot
(2% of the canvas) so even point-objects like lights remain clickable.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Hotspots smaller than this in either axis would be impossible to
# hover. Bump them up to keep the interaction usable.
_MIN_SIDE = 0.02
# Hotspots larger than this consume too much of the image. Cap them
# so a poorly-dimensioned object doesn't blanket the click area.
_MAX_SIDE = 0.4


def compute_object_bboxes(graph_data: Any) -> list[dict[str, Any]]:
    """Return a list of ``{id, name, type, x, y, w, h}`` hotspots.

    Each rect is normalised to [0, 1] in both axes — the frontend
    multiplies by the rendered image's box size to get pixel positions.
    Returns ``[]`` for malformed input rather than raising; callers
    treat hotspots as best-effort.
    """
    if not isinstance(graph_data, dict):
        return []

    room = _room_dimensions(graph_data)
    objects = graph_data.get("objects") or []
    if not room or not isinstance(objects, list):
        return []

    room_length, room_width = room
    if room_length <= 0 or room_width <= 0:
        return []

    out: list[dict[str, Any]] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        oid = obj.get("id")
        if not oid:
            continue
        pos = obj.get("position") or {}
        dims = obj.get("dimensions") or {}
        ox = _num(pos.get("x"))
        oy = _num(pos.get("y"))
        if ox is None or oy is None:
            continue
        ol = _num(dims.get("length"))
        ow = _num(dims.get("width"))

        # Normalise position (the centre of the object's footprint).
        cx = ox / room_length
        cy = oy / room_width

        # Normalise size; fall back to MIN_SIDE for point-objects.
        w = (ol or 0) / room_length if ol else _MIN_SIDE
        h = (ow or 0) / room_width if ow else _MIN_SIDE
        w = _clamp(w, _MIN_SIDE, _MAX_SIDE)
        h = _clamp(h, _MIN_SIDE, _MAX_SIDE)

        # Convert centre → top-left corner; clamp to [0,1] so the rect
        # doesn't bleed off the canvas if the object's centre sits
        # near a wall.
        x = _clamp(cx - w / 2, 0.0, 1.0 - w)
        y = _clamp(cy - h / 2, 0.0, 1.0 - h)

        out.append({
            "id": oid,
            "name": (obj.get("name") or "").strip() or _format_type(obj.get("type", "")),
            "type": obj.get("type") or "object",
            "x": round(x, 4),
            "y": round(y, 4),
            "w": round(w, 4),
            "h": round(h, 4),
        })

    return out


# ── helpers ────────────────────────────────────────────────────────────


def _room_dimensions(graph_data: dict) -> tuple[float, float] | None:
    """Return (length, width) of the first non-empty space, or None."""
    spaces = graph_data.get("spaces") or []
    for s in spaces:
        if not isinstance(s, dict):
            continue
        d = s.get("dimensions") or {}
        length = _num(d.get("length"))
        width = _num(d.get("width"))
        if length and width and length > 0 and width > 0:
            return length, width
    return None


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _format_type(t: str) -> str:
    if not t:
        return "Object"
    s = t.replace("_", " ")
    return s[0].upper() + s[1:] if s else "Object"
