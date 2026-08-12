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
        ("desk", (1.6, 0.8), 0.75, "back"),
        ("chair", (0.5, 0.5), 0.9, "center"),
        ("wardrobe", (1.2, 0.5), 1.9, "left"),   # storage cabinet
    ],
    # ── workplace / commercial ──────────────────────────────────────────────
    "reception": [
        ("reception_desk", (2.0, 0.7), 1.05, "back"),
        ("sofa", (1.8, 0.8), 0.8, "front"),      # waiting seating
    ],
    "meeting": [
        ("conference_table", (2.6, 1.2), 0.75, "center"),
    ],
    "workspace": [                               # open-plan → a row of desks
        ("desk", (1.4, 0.7), 0.75, "left"),
        ("desk", (1.4, 0.7), 0.75, "center"),
        ("desk", (1.4, 0.7), 0.75, "right"),
    ],
    "waiting": [
        ("sofa", (2.0, 0.9), 0.8, "back"),
        ("coffee_table", (1.0, 0.6), 0.45, "center"),
    ],
    "retail": [
        ("counter", (2.0, 0.6), 0.95, "back"),
        ("shelf", (1.6, 0.5), 1.8, "left"),
        ("shelf", (1.6, 0.5), 1.8, "right"),
    ],
}


def _category(text: str) -> str:
    """Room name/type → furniture category. Unknown / service → '' (no furniture).

    Workplace/commercial types are matched first (they're more specific), then
    residential.
    """
    t = (text or "").lower()
    # workplace / commercial
    if "reception" in t:
        return "reception"
    if any(k in t for k in ("meeting", "conference", "boardroom")):
        return "meeting"
    if any(k in t for k in ("workspace", "workstation", "open plan", "open-plan", "bullpen", "cubicle")):
        return "workspace"
    if any(k in t for k in ("waiting", "lobby")):
        return "waiting"
    if any(k in t for k in ("retail", "shop", "showroom", "boutique", "storefront")):
        return "retail"
    if any(k in t for k in ("cafe", "restaurant", "canteen", "cafeteria")):
        return "dining"
    # residential
    if "kitchen" in t or "pantry" in t:
        return "kitchen"
    if "wc" in t or "toilet" in t or "powder" in t:
        return "wc"
    if any(k in t for k in ("bath", "shower", "washroom", "ensuite")):
        return "bathroom"
    if "dining" in t:
        return "dining"
    if any(k in t for k in ("office", "cabin", "study", "work")):
        return "office"
    if any(k in t for k in ("living", "lounge", "family", "drawing")):
        return "living"
    if any(k in t for k in ("bed", "master", "guest")):
        return "bedroom"
    return ""


def _rect(cx: float, cz: float, fl: float, fw: float) -> tuple[float, float, float, float]:
    return (cx - fl / 2, cz - fw / 2, cx + fl / 2, cz + fw / 2)


def _overlaps(a: tuple, b: tuple, clear: float) -> bool:
    return (a[0] < b[2] + clear and a[2] > b[0] - clear
            and a[1] < b[3] + clear and a[3] > b[1] - clear)


def _candidates(placement: str, x0: float, z0: float, length: float, width: float,
                fl: float, fw: float, margin: float) -> list[tuple[float, float]]:
    """Ordered candidate centres — ideal spot first, then slide along the wall
    (centre-out) so a blocked piece steps aside instead of stacking."""
    xlo, xhi = x0 + fl / 2, x0 + length - fl / 2
    zlo, zhi = z0 + fw / 2, z0 + width - fw / 2

    def scan(lo: float, hi: float, n: int = 9) -> list[float]:
        if hi <= lo:
            return [(lo + hi) / 2]
        pts = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
        pts.sort(key=lambda v: abs(v - (lo + hi) / 2))  # centre-out
        return pts

    if placement in ("back", "front"):
        cz = (z0 + width - fw / 2 - margin) if placement == "back" else (z0 + fw / 2 + margin)
        cz = min(max(cz, zlo), zhi)
        return [(x, cz) for x in scan(xlo, xhi)]
    if placement in ("left", "right"):
        cx = (x0 + fl / 2 + margin) if placement == "left" else (x0 + length - fl / 2 - margin)
        cx = min(max(cx, xlo), xhi)
        return [(cx, z) for z in scan(zlo, zhi)]
    if placement == "corner":
        return [(xlo, zlo), (xhi, zlo), (xlo, zhi), (xhi, zhi), ((xlo + xhi) / 2, (zlo + zhi) / 2)]
    # center — small centre-out grid
    cands: list[tuple[float, float]] = []
    for x in scan(xlo, xhi, 5):
        for z in scan(zlo, zhi, 5):
            cands.append((x, z))
    return cands


def _place_free(placement: str, x0: float, z0: float, length: float, width: float,
                fl: float, fw: float, occupied: list, margin: float,
                clear: float) -> tuple[float, float] | None:
    """First candidate centre that fits inside the room and clears every
    already-placed piece. ``None`` when nothing fits (piece is dropped)."""
    for cx, cz in _candidates(placement, x0, z0, length, width, fl, fw, margin):
        r = _rect(cx, cz, fl, fw)
        if (r[0] < x0 - 1e-6 or r[1] < z0 - 1e-6
                or r[2] > x0 + length + 1e-6 or r[3] > z0 + width + 1e-6):
            continue
        if any(_overlaps(r, o, clear) for o in occupied):
            continue
        return cx, cz
    return None


# If a piece can't sit on its preferred wall (blocked by the anchor piece),
# try the others before giving up — a wardrobe crowded off the side walls
# still belongs at the foot of the bed rather than nowhere.
_FALLBACKS: dict[str, list[str]] = {
    "left": ["left", "right", "back", "front"],
    "right": ["right", "left", "back", "front"],
    "back": ["back", "front", "left", "right"],
    "front": ["front", "back", "left", "right"],
    "center": ["center", "back", "front"],
    "corner": ["corner", "back", "front", "left", "right"],
}


def _furnish_one(space: dict) -> list[dict]:
    cat = _category(str(space.get("room_type") or space.get("name") or ""))
    if not cat:
        return []
    x0, z0 = float(space["position"]["x"]), float(space["position"]["z"])
    length, width = float(space["dimensions"]["length"]), float(space["dimensions"]["width"])
    margin, clear = 0.12, 0.06
    occupied: list[tuple] = []   # rects of pieces already placed in this room
    out: list[dict] = []
    # Catalogue order is anchor-first (bed / sofa / counter before the rest), so
    # the big piece claims its spot and smaller ones route around it.
    for ftype, (fl0, fw0), height, placement in _FURNITURE.get(cat, []):
        placed: tuple | None = None
        for pl in _FALLBACKS.get(placement, [placement]):
            # Rotate wall-hugging pieces so their depth faces the side wall — a
            # wardrobe against a side wall is 0.6 m deep and 1.6 m along it, not
            # a 1.6 m slab jutting into the room. Re-derive per candidate wall.
            fl, fw = (fw0, fl0) if pl in ("left", "right") else (fl0, fw0)
            fl2 = min(fl, length - 2 * clear)   # keep real sizes; only trim to fit
            fw2 = min(fw, width - 2 * clear)
            if fl2 <= 0.1 or fw2 <= 0.1:
                continue
            spot = _place_free(pl, x0, z0, length, width, fl2, fw2, occupied, margin, clear)
            if spot is not None:
                placed = (spot[0], spot[1], fl2, fw2)
                break
        if placed is None:
            continue  # no non-overlapping fit on any wall — omit rather than stack
        cx, cz, fl2, fw2 = placed
        occupied.append(_rect(cx, cz, fl2, fw2))
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
