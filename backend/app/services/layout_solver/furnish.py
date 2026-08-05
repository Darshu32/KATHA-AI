"""Deterministic per-room furnishing for a solved multi-room plan.

The LLM authors furniture in a single-room frame, so in a multi-room plan its
objects land in the wrong rooms (or off in a corner) and the finish pass ends up
hallucinating furniture to fill the gaps. This places a small, room-appropriate
set of furniture in WORLD coordinates inside each solved room, so the render /
plan / 3D / IFC show furnished rooms grounded in the actual geometry.

Footprints are standard furniture sizes in metres — layout parameters, not
design output; a richer catalogue or LLM per-room furnishing can replace this
later. Service rooms (hall / corridor) are left clear.
"""

from __future__ import annotations

# room category → [(type, (length_x, width_z) m, height m, placement)]
_FURNITURE: dict[str, list] = {
    "living": [
        ("sofa", (2.1, 0.9), 0.8, "back"),
        ("coffee_table", (1.1, 0.6), 0.45, "center"),
        ("tv_unit", (1.6, 0.4), 0.5, "front"),
    ],
    "bedroom": [
        ("bed", (2.0, 1.6), 0.5, "back"),
        ("wardrobe", (1.6, 0.6), 2.0, "left"),
    ],
    "kitchen": [
        ("counter", (2.2, 0.6), 0.9, "back"),
        ("appliance", (0.7, 0.7), 1.8, "left"),
    ],
    "dining": [
        ("dining_table", (1.6, 0.9), 0.75, "center"),
    ],
    "bathroom": [
        ("wc", (0.6, 0.5), 0.4, "corner"),
        ("basin", (0.6, 0.45), 0.85, "front"),
    ],
    "wc": [
        ("wc", (0.6, 0.5), 0.4, "corner"),
    ],
    "office": [
        ("desk", (1.4, 0.7), 0.75, "back"),
        ("chair", (0.5, 0.5), 0.9, "center"),
    ],
}


def _category(text: str) -> str:
    """Room name/type → furniture category. Unknown / service → '' (no furniture)."""
    t = (text or "").lower()
    if "kitchen" in t:
        return "kitchen"
    if "wc" in t or "toilet" in t or "powder" in t:
        return "wc"
    if any(k in t for k in ("bath", "shower", "washroom", "ensuite")):
        return "bathroom"
    if "dining" in t:
        return "dining"
    if any(k in t for k in ("office", "study", "work")):
        return "office"
    if any(k in t for k in ("living", "lounge", "family", "drawing")):
        return "living"
    if any(k in t for k in ("bed", "master", "guest")):
        return "bedroom"
    return ""


def _place(placement: str, x0: float, z0: float, length: float, width: float,
           fl: float, fw: float, margin: float = 0.12) -> tuple[float, float]:
    """Centre (cx, cz) of a piece, kept inside the room rectangle."""
    if placement == "back":
        cx, cz = x0 + length / 2, z0 + width - fw / 2 - margin
    elif placement == "front":
        cx, cz = x0 + length / 2, z0 + fw / 2 + margin
    elif placement == "left":
        cx, cz = x0 + fl / 2 + margin, z0 + width / 2
    elif placement == "right":
        cx, cz = x0 + length - fl / 2 - margin, z0 + width / 2
    elif placement == "corner":
        cx, cz = x0 + fl / 2 + margin, z0 + fw / 2 + margin
    else:  # center
        cx, cz = x0 + length / 2, z0 + width / 2
    cx = min(max(cx, x0 + fl / 2), x0 + length - fl / 2)
    cz = min(max(cz, z0 + fw / 2), z0 + width - fw / 2)
    return cx, cz


def _furnish_one(space: dict) -> list[dict]:
    cat = _category(str(space.get("room_type") or space.get("name") or ""))
    if not cat:
        return []
    x0, z0 = float(space["position"]["x"]), float(space["position"]["z"])
    length, width = float(space["dimensions"]["length"]), float(space["dimensions"]["width"])
    out: list[dict] = []
    for ftype, (fl, fw), height, placement in _FURNITURE.get(cat, []):
        fl2, fw2 = min(fl, length * 0.85), min(fw, width * 0.85)  # shrink to fit
        if fl2 <= 0.1 or fw2 <= 0.1:
            continue
        cx, cz = _place(placement, x0, z0, length, width, fl2, fw2)
        out.append({
            "id": f"{space['id']}_{ftype}",
            "type": ftype,
            "name": ftype.replace("_", " ").title(),
            "position": {"x": round(cx, 3), "y": 0.0, "z": round(cz, 3)},
            "dimensions": {"length": round(fl2, 3), "width": round(fw2, 3), "height": height},
            "role": "furniture",
        })
    return out


def furnish_rooms(graph: dict) -> dict:
    """Return a copy of ``graph`` whose ``objects`` are room-appropriate furniture
    placed in world coordinates inside each solved room. Multi-room only — a graph
    with fewer than two placed rooms is returned unchanged.
    """
    spaces = [
        s for s in (graph.get("spaces") or [])
        if isinstance(s, dict) and isinstance(s.get("position"), dict) and isinstance(s.get("dimensions"), dict)
    ]
    if len(spaces) < 2:
        return graph
    objects: list[dict] = []
    for space in spaces:
        objects.extend(_furnish_one(space))
    out = dict(graph)
    out["objects"] = objects
    return out
