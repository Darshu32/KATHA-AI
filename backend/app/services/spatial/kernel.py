"""Geometry kernel — DesignGraph spec → real solids via Manifold.

The LLM never emits geometry; this deterministic kernel builds it. Objects
become unit-correct boxes at their spec position; interiors gain a floor + four
tagged perimeter walls; void-typed spaces (atrium/courtyard) are *subtracted*
from the mass they sit in — a real boolean the box-only glTF path cannot do.
Output is per-object :class:`Solid` (mesh + colour + id + side) so the renderer
can shade them and project exact hotspots.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from manifold3d import Manifold

from app.services.wall_model import derive_multiroom_wall_model, derive_wall_model

# ── units ────────────────────────────────────────────────────────────────────
_UNIT_TO_M = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "metre": 1.0, "meter": 1.0,
              "ft": 0.3048, "feet": 0.3048, "foot": 0.3048, "in": 0.0254}


def _to_m(value, unit: str | None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if unit:  # trust the explicit unit (graph_normalizer stamps "m")
        return v * _UNIT_TO_M.get(str(unit).strip().lower(), 1.0)
    return v / 1000.0 if abs(v) > 30 else v  # only guess when unit is absent


# ── colour ───────────────────────────────────────────────────────────────────
_CSS = {
    "white": (0.93, 0.93, 0.93), "black": (0.12, 0.12, 0.12), "grey": (0.55, 0.55, 0.55),
    "gray": (0.55, 0.55, 0.55), "green": (0.35, 0.55, 0.32), "red": (0.78, 0.25, 0.2),
    "blue": (0.3, 0.45, 0.7), "turquoise": (0.25, 0.68, 0.66), "brown": (0.45, 0.33, 0.24),
    "tan": (0.76, 0.68, 0.5), "beige": (0.83, 0.78, 0.66), "transparent": (0.7, 0.82, 0.88),
    "glass": (0.7, 0.82, 0.88), "silver": (0.75, 0.76, 0.78), "gold": (0.8, 0.68, 0.35),
}
_TYPE_DEFAULT = {
    "building": (0.86, 0.85, 0.82), "wall": (0.9, 0.89, 0.86), "floor": (0.72, 0.69, 0.64),
    "slab": (0.72, 0.69, 0.64), "pool": (0.3, 0.6, 0.72), "tree": (0.34, 0.5, 0.32),
    "driveway": (0.6, 0.6, 0.62), "column": (0.72, 0.72, 0.74), "atrium": (0.7, 0.82, 0.88),
    "roof": (0.5, 0.42, 0.38), "ground": (0.82, 0.83, 0.8), "sofa": (0.55, 0.5, 0.46),
    "table": (0.6, 0.45, 0.32), "bed": (0.7, 0.66, 0.6), "chair": (0.5, 0.45, 0.4),
    "rug": (0.7, 0.5, 0.45), "cabinet": (0.55, 0.42, 0.3),
    # Facade screens / brise-soleil default to a stained-timber tone.
    "screen": (0.36, 0.26, 0.18), "louver": (0.36, 0.26, 0.18),
    "louvre": (0.36, 0.26, 0.18), "brise_soleil": (0.36, 0.26, 0.18),
    "slats": (0.36, 0.26, 0.18), "jali": (0.58, 0.48, 0.38),
}


def _parse_color(raw, fallback=(0.78, 0.76, 0.72)):
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in _CSS:
            return _CSS[s]
        v = s.lstrip("#")
        if len(v) == 6:
            try:
                return int(v[0:2], 16) / 255, int(v[2:4], 16) / 255, int(v[4:6], 16) / 255
            except ValueError:
                pass
    return fallback


# Architectural material → representative colour. Scanned as substrings (first
# hit wins, specifics first) so a descriptive material string like "pale
# cream-beige Roman brick" or "dark stained timber" resolves to a sensible tone
# in the clay render — no img2img, no external service, fully deterministic.
_MATERIAL_COLORS = [
    ("terracotta", (0.72, 0.42, 0.30)), ("brick", (0.78, 0.60, 0.48)),
    ("sandstone", (0.82, 0.72, 0.55)), ("limestone", (0.85, 0.82, 0.72)),
    ("travertine", (0.84, 0.78, 0.66)), ("marble", (0.90, 0.89, 0.86)),
    ("granite", (0.50, 0.49, 0.48)), ("slate", (0.36, 0.39, 0.42)),
    ("stone", (0.70, 0.68, 0.62)), ("concrete", (0.68, 0.67, 0.64)),
    ("plaster", (0.88, 0.86, 0.80)), ("stucco", (0.87, 0.84, 0.77)),
    ("render", (0.86, 0.84, 0.78)), ("teak", (0.55, 0.38, 0.23)),
    ("walnut", (0.40, 0.28, 0.19)), ("oak", (0.62, 0.48, 0.32)),
    ("timber", (0.52, 0.37, 0.24)), ("wood", (0.55, 0.40, 0.26)),
    ("bamboo", (0.74, 0.62, 0.40)), ("corten", (0.55, 0.34, 0.24)),
    ("copper", (0.72, 0.45, 0.30)), ("bronze", (0.55, 0.44, 0.28)),
    ("steel", (0.62, 0.64, 0.67)), ("aluminium", (0.72, 0.74, 0.76)),
    ("aluminum", (0.72, 0.74, 0.76)), ("metal", (0.60, 0.62, 0.65)),
    ("cream", (0.90, 0.86, 0.76)), ("ivory", (0.92, 0.90, 0.82)),
    ("charcoal", (0.26, 0.26, 0.27)),
]


def _material_color(name) -> tuple | None:
    """Resolve a descriptive material string to a colour, or None.

    Substring-matches architectural materials and the basic CSS palette, then
    applies simple tone modifiers ("pale"/"light" lighten, "dark" darkens) so
    "pale cream-beige brick" reads light and "dark stained timber" reads deep.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    s = name.lower()
    hit = next((rgb for kw, rgb in _MATERIAL_COLORS if kw in s), None)
    if hit is None:
        # Basic CSS colours are short words ("tan", "red") — match on word
        # boundaries so "tan" doesn't fire inside "unobtanium"/"titanium".
        words = set(s.replace("-", " ").replace("/", " ").split())
        hit = next((rgb for kw, rgb in _CSS.items() if kw in words), None)
    if hit is None:
        return None
    if any(w in s for w in ("dark", "charcoal", "ebony", "espresso", "walnut stain")):
        hit = tuple(c * 0.72 for c in hit)
    elif any(w in s for w in ("pale", "light", "off-white", "bleached", "whitewash")):
        hit = tuple(min(1.0, c * 0.55 + 0.45) for c in hit)
    return hit


def _color_for(obj: dict, materials_by_key: dict) -> tuple:
    c = obj.get("color")
    if isinstance(c, str) and c.strip():
        parsed = _parse_color(c, None)
        if parsed:
            return parsed
    mref = obj.get("material")
    if isinstance(mref, str) and mref.strip():
        mat = materials_by_key.get(mref) or materials_by_key.get(mref.lower())
        if mat:
            parsed = _parse_color(mat.get("color"), None)
            if parsed:
                return parsed
            named = _material_color(mat.get("name") or mref)
            if named:
                return named
        named = _material_color(mref)  # resolve the descriptive material string
        if named:
            return named
    return _TYPE_DEFAULT.get(str(obj.get("type", "")).lower(), (0.78, 0.76, 0.72))


# ── geometry ─────────────────────────────────────────────────────────────────
_VOID_TYPES = {"atrium", "courtyard", "void", "shaft", "lightwell", "cutout"}
# Facade screens: one object → an ARRAY of thin slat solids (a brise-soleil /
# louvre / timber screen), not a single box. Built by ``_screen_slats``.
_SCREEN_TYPES = {"screen", "louver", "louvre", "louvers", "louvres",
                 "brise_soleil", "brise-soleil", "slats", "grille", "jali"}
# Object types that hang on a wall / ceiling and keep their authored height;
# everything else is floor-placed (the LLM's vertical coordinate is unreliable —
# often depth, which otherwise floats the piece metres off the floor).
_WALL_MOUNTED = {"tv", "television", "light", "lamp", "chandelier", "pendant",
                 "sconce", "painting", "mirror", "artwork", "clock", "wall_shelf",
                 "shelf", "ac", "air_conditioner", "fan", "ceiling_fan"}
_WALL_T = 0.1        # interior wall thickness (m)
_DEFAULT_ROOM_H = 2.8


@dataclass
class Solid:
    id: str
    name: str
    type: str
    color: tuple
    manifold: object
    side: str | None = None                 # "+x"/"-x"/"+z"/"-z" for cullable walls
    verts: np.ndarray = field(default=None)  # (N,3) world
    tris: np.ndarray = field(default=None)   # (M,3) int


def _box(l: float, h: float, w: float, cx: float, cy: float, cz: float, rot_y_deg: float = 0.0):
    """Box (l,h,w) centred in X/Z, base at y=0, rotated about its vertical
    centreline, placed so its centre-base sits at (cx,cy,cz)."""
    l, h, w = max(l, 1e-3), max(h, 1e-3), max(w, 1e-3)
    m = Manifold.cube((l, h, w), False).translate((-l / 2, 0.0, -w / 2))
    if abs(rot_y_deg) > 1e-6:
        m = m.rotate((0.0, rot_y_deg, 0.0))
    return m.translate((cx, cy, cz))


def _screen_slats(obj: dict, unit: str | None) -> list:
    """Expand a screen/louvre/brise-soleil object into an ARRAY of thin slat
    boxes across its region — the geometry a single box can never represent.

    The region is the object's footprint (position = centre-base) × height.
    ``orientation`` picks the slat run: "horizontal" (default) stacks slats up
    the Y axis; "vertical" stacks them across X. Slat count comes from
    ``slat_count`` or is derived from ``slat_thickness`` + ``slat_gap``. An
    optional ``gradient`` ("top"/"bottom") biases the spacing denser toward that
    end — the signature move of a screen that reads solid at the top and opens up
    lower down. Rotation about vertical is honoured so an angled screen works.
    """
    d = obj.get("dimensions") or {}
    L = _to_m(d.get("length"), unit) or 2.0     # x extent
    Wd = _to_m(d.get("width"), unit) or 0.12    # z depth of each slat
    H = _to_m(d.get("height"), unit) or 2.0     # y extent
    p = obj.get("position") or {}
    cx, cy, cz = float(p.get("x", 0) or 0), float(p.get("y", 0) or 0), float(p.get("z", 0) or 0)
    rot = (obj.get("rotation") or {}).get("y", 0) or 0 if isinstance(obj.get("rotation"), dict) else 0

    vertical = str(obj.get("orientation") or "horizontal").lower().startswith("vert")
    span = L if vertical else H
    t = _to_m(obj.get("slat_thickness"), unit) or 0.05
    gap = _to_m(obj.get("slat_gap"), unit) or max(t, 0.05)
    count = obj.get("slat_count")
    n = int(count) if count else max(2, int(span / max(t + gap, 1e-3)))
    n = max(2, min(n, 48))  # cap for performance — 48 slats is plenty

    grad = str(obj.get("gradient") or "").lower()
    gamma = 0.55 if grad in ("top", "top_dense", "dense_top") else \
        (1.8 if grad in ("bottom", "bottom_dense", "dense_bottom") else 1.0)
    usable = max(span - t, 1e-3)

    slats = []
    for i in range(n):
        f = i / (n - 1)
        pos = usable * (f ** gamma)
        if vertical:
            slats.append(_box(t, H, Wd, cx - L / 2 + t / 2 + pos, cy, cz, float(rot)))
        else:
            slats.append(_box(L, t, Wd, cx, cy + pos, cz, float(rot)))
    return slats


# Object types that mean "this is a site/building, not a room" — so a large
# `spaces` entry (e.g. a 60×60×12 plot) is treated as exterior, not walled.
_SITE_TYPES = {"building", "tower", "block", "site", "plot", "driveway", "road",
               "parking", "landscape", "bridge", "pavilion"}


def _is_interior(graph: dict, room_l: float, room_w: float, room_h: float) -> bool:
    """A room, not a site: bounded, room-scale footprint, room-scale ceiling,
    and no site/building-scale objects."""
    if not (0.5 < room_l <= 30 and 0.5 < room_w <= 30):
        return False
    if not (0.0 < room_h <= 5.0):          # a 12 m "space" is a site, not a room
        return False
    for o in graph.get("objects") or []:
        if isinstance(o, dict) and str(o.get("type", "")).lower() in _SITE_TYPES:
            return False
    return True


def _room_dims(graph: dict) -> tuple[float, float, float]:
    space = None
    spaces = graph.get("spaces")
    if isinstance(spaces, list) and spaces and isinstance(spaces[0], dict):
        space = spaces[0]
    elif isinstance(graph.get("room"), dict):
        space = graph["room"]
    d = (space or {}).get("dimensions") if isinstance(space, dict) else None
    d = d if isinstance(d, dict) else {}
    unit = d.get("unit")
    return (_to_m(d.get("length"), unit), _to_m(d.get("width"), unit),
            _to_m(d.get("height"), unit) or _DEFAULT_ROOM_H)


# Map wall_model sides to the kernel's cull tags (the renderer drops the near
# walls facing the camera for the dollhouse interior view).
_SIDE_TAG = {"south": "-z", "north": "+z", "west": "-x", "east": "+x"}


def _wall_solids(graph: dict) -> tuple[list[Solid], set[str]]:
    """Floor + four perimeter walls with REAL window/door openings cut in
    (Manifold voids), from the shared ``derive_wall_model`` — the same source the
    IFC export and section/elevation drawings read. Returns the solids plus the
    set of opening object-ids so the caller can skip rendering those as boxes."""
    wm = derive_wall_model(graph)
    L = float(wm["room"]["length"])
    W = float(wm["room"]["width"])
    H = float(wm["room"]["height"])
    t = float(wm["thickness"])
    wc = _TYPE_DEFAULT["wall"]
    out: list[Solid] = [
        Solid("floor", "Floor", "floor", _TYPE_DEFAULT["floor"], _box(L, 0.05, W, L / 2, -0.05, W / 2)),
    ]
    opening_ids: set[str] = set()
    for wall in wm["walls"]:
        side = wall["side"]
        if side == "south":
            m = _box(L, H, t, L / 2, 0.0, 0.0)
        elif side == "north":
            m = _box(L, H, t, L / 2, 0.0, W)
        elif side == "west":
            m = _box(t, H, W, 0.0, 0.0, W / 2)
        else:  # east
            m = _box(t, H, W, L, 0.0, W / 2)
        for op in wall["openings"]:
            c = float(op["center"])
            w = float(op["width"])
            sill = float(op["sill"])
            oh = max(float(op["head"]) - sill, 0.05)
            if side in ("south", "north"):
                at_z = 0.0 if side == "south" else W
                m = m - _box(w, oh, t * 3, c, sill, at_z)  # void through the wall
            else:
                at_x = 0.0 if side == "west" else L
                m = m - _box(t * 3, oh, w, at_x, sill, c)
            sid = op.get("source_id")
            if sid:
                opening_ids.add(str(sid))
        out.append(Solid(str(wall["id"]), "Wall", "wall", wc, m, side=_SIDE_TAG[side]))
    return out, opening_ids


def _placed_rooms(graph: dict) -> list[dict]:
    """Spaces carrying an explicit position + dimensions → room dicts (metres).

    Non-empty only for a *solved* plan (after ``layout_solver.apply_layout_to_graph``);
    two or more of these switch ``build_scene`` onto the multi-room path.
    """
    out: list[dict] = []
    for i, s in enumerate(graph.get("spaces") or []):
        if not isinstance(s, dict):
            continue
        pos, d = s.get("position"), s.get("dimensions")
        if not (isinstance(pos, dict) and isinstance(d, dict)):
            continue
        unit = d.get("unit")
        L, Wd = _to_m(d.get("length"), unit), _to_m(d.get("width"), unit)
        if L <= 0 or Wd <= 0:
            continue
        out.append({
            "id": str(s.get("id") or s.get("name") or f"space_{i + 1}"),
            "x": _to_m(pos.get("x"), unit), "z": _to_m(pos.get("z"), unit),
            "length": L, "width": Wd,
            "height": _to_m(d.get("height"), unit) or _DEFAULT_ROOM_H,
        })
    return out


def _segment_box(seg: dict):
    """A wall segment → a box centered on its line (centerline convention)."""
    t = float(seg["thickness"])
    h = float(seg["height"]) or _DEFAULT_ROOM_H
    a, b, at = float(seg["start"]), float(seg["end"]), float(seg["at"])
    length = max(b - a, 1e-3)
    if seg["runs"] == "z":            # vertical wall: thin in x, long in z
        return _box(t, h, length, at, 0.0, (a + b) / 2)
    return _box(length, h, t, (a + b) / 2, 0.0, at)  # horizontal: long in x, thin in z


def _multiroom_solids(rooms: list[dict], adjacencies: list | None = None) -> list[Solid]:
    """A floor slab per room + partition/exterior wall solids from the shared
    ``derive_multiroom_wall_model``, with **real openings cut in** — doors in
    partitions between adjacent rooms, windows on exterior walls (Manifold
    voids, the same way the single-room path cuts them). Each wall is tagged with
    the room(s) it bounds."""
    solids: list[Solid] = []
    fc = _TYPE_DEFAULT["floor"]
    for r in rooms:
        solids.append(Solid(
            f"floor_{r['id']}", f"Floor · {r['id']}", "floor", fc,
            _box(r["length"], 0.05, r["width"], r["x"] + r["length"] / 2, -0.05, r["z"] + r["width"] / 2),
        ))
    wc = _TYPE_DEFAULT["wall"]
    # Shared default thickness + adjacency-driven openings so the 3D matches the
    # IFC export exactly.
    for seg in derive_multiroom_wall_model(rooms, adjacencies):
        m = _segment_box(seg)
        t = float(seg["thickness"])
        for op in seg.get("openings", []):
            c = float(seg["start"]) + float(op["center"])   # absolute along the run axis
            w = float(op["width"])
            sill = float(op["sill"])
            oh = max(float(op["head"]) - sill, 0.05)
            if seg["runs"] == "z":       # wall thin in x → void through x
                m = m - _box(t * 3, oh, w, float(seg["at"]), sill, c)
            else:                         # wall thin in z → void through z
                m = m - _box(w, oh, t * 3, c, sill, float(seg["at"]))
        solids.append(Solid(seg["id"], f"Wall · {'/'.join(seg['rooms'])}", "wall", wc, m, side=None))
    return solids


def build_scene(graph: dict) -> tuple[list[Solid], tuple, str]:
    """Spec → (solids with meshes, scene AABB, kind) where kind∈{interior,exterior}."""
    materials_by_key: dict = {}
    for mat in graph.get("materials") or []:
        if isinstance(mat, dict):
            for k in (mat.get("id"), mat.get("name")):
                if isinstance(k, str) and k:
                    materials_by_key[k] = mat
                    materials_by_key[k.lower()] = mat

    room_l, room_w, room_h = _room_dims(graph)
    interior = _is_interior(graph, room_l, room_w, room_h)
    # An explicit architectural / exterior / product scope forces the object
    # render path (ground + solids), not the interior walls path.
    scope = str(graph.get("design_type") or "").lower()
    if scope in ("architecture", "exterior", "product"):
        interior = False

    raw = []
    screen_objs = []
    for obj in graph.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        otype = str(obj.get("type") or "").lower()
        # A screen/louvre is one object → many slats; expand it separately.
        if otype in _SCREEN_TYPES:
            screen_objs.append(obj)
            continue
        d = obj.get("dimensions") or {}
        unit = d.get("unit")
        l = _to_m(d.get("length"), unit) or 0.4
        w = _to_m(d.get("width"), unit) or 0.4
        h = _to_m(d.get("height"), unit) or 0.4
        p = obj.get("position") or {}
        cx, cz = float(p.get("x", 0) or 0), float(p.get("z", 0) or 0)
        # Floor-place furniture in INTERIORS (the LLM's vertical coord is
        # unreliable there). Keep the authored height for wall/ceiling items, and
        # for exterior massing (multi-storey volumes must keep their level).
        cy = 0.0 if (interior and otype not in _WALL_MOUNTED) else float(p.get("y", 0) or 0)
        rot = (obj.get("rotation") or {}).get("y", 0) or 0
        raw.append((obj, _box(l, h, w, cx, cy, cz, float(rot))))

    # Voids carve the mass they sit in.
    voids = [(o, m) for o, m in raw if str(o.get("type", "")).lower() in _VOID_TYPES]
    body = [(o, m) for o, m in raw if str(o.get("type", "")).lower() not in _VOID_TYPES]
    if voids:
        cut = []
        for o, m in body:
            for _, vm in voids:
                vv = vm.volume() or 1e-9
                if (m ^ vm).volume() > 0.30 * vv:
                    m = m - vm
            cut.append((o, m))
        body = cut

    solids: list[Solid] = []

    opening_ids: set[str] = set()
    if interior:
        placed = _placed_rooms(graph)
        if len(placed) >= 2:
            # Multi-room: floor-per-room + shared-partition walls with real
            # doors (from adjacencies) and windows cut in.
            solids.extend(_multiroom_solids(placed, graph.get("adjacencies")))
        else:
            # Single room: floor + four perimeter walls with real openings cut in.
            wall_solids, opening_ids = _wall_solids(graph)
            solids.extend(wall_solids)
    else:
        # Site-scale: a ground plane under the massing.
        cxz = _center_xz(body)
        span = _scene_span(body)
        solids.append(Solid("ground", "Ground", "ground", _TYPE_DEFAULT["ground"],
                            _box(2.4 * span, 0.05, 2.4 * span, cxz[0], -0.05, cxz[1])))

    for o, m in body:
        oid = str(o.get("id") or o.get("name") or "obj")
        # A window/door object is now a real void in a wall — don't also draw it
        # as a floating box.
        if interior and oid in opening_ids:
            continue
        solids.append(Solid(
            id=oid,
            name=str(o.get("name") or o.get("type") or "object"),
            type=str(o.get("type") or "object"),
            color=_color_for(o, materials_by_key), manifold=m,
        ))

    # Facade screens: each becomes an array of slat solids (a real brise-soleil).
    for so in screen_objs:
        unit = (so.get("dimensions") or {}).get("unit")
        color = _color_for(so, materials_by_key)
        base_id = str(so.get("id") or so.get("name") or "screen")
        sname = str(so.get("name") or so.get("type") or "screen")
        for j, sm in enumerate(_screen_slats(so, unit)):
            solids.append(Solid(f"{base_id}_slat{j}", sname, "screen", color, sm))

    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for s in solids:
        mesh = s.manifold.to_mesh()
        s.verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        s.tris = np.asarray(mesh.tri_verts, dtype=np.int64)
        if len(s.verts):
            lo = np.minimum(lo, s.verts.min(0))
            hi = np.maximum(hi, s.verts.max(0))
    kind = "product" if scope == "product" else ("interior" if interior else "exterior")
    return solids, (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]), kind


def _bounds_xz(pairs):
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for _, m in pairs:
        b = m.bounding_box()
        lo = np.minimum(lo, b[:3])
        hi = np.maximum(hi, b[3:])
    return lo, hi


def _scene_span(pairs) -> float:
    if not pairs:
        return 1.0
    lo, hi = _bounds_xz(pairs)
    return float(max(hi[0] - lo[0], hi[2] - lo[2], 1.0))


def _center_xz(pairs) -> tuple:
    if not pairs:
        return (0.0, 0.0)
    lo, hi = _bounds_xz(pairs)
    return (float((lo[0] + hi[0]) / 2), float((lo[2] + hi[2]) / 2))
