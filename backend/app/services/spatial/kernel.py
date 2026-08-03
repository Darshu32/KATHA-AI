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


def _color_for(obj: dict, materials_by_key: dict) -> tuple:
    c = obj.get("color")
    if isinstance(c, str) and c.strip():
        parsed = _parse_color(c, None)
        if parsed:
            return parsed
    mref = obj.get("material")
    if isinstance(mref, str):
        mat = materials_by_key.get(mref) or materials_by_key.get(mref.lower())
        if mat:
            parsed = _parse_color(mat.get("color"), None)
            if parsed:
                return parsed
    return _TYPE_DEFAULT.get(str(obj.get("type", "")).lower(), (0.78, 0.76, 0.72))


# ── geometry ─────────────────────────────────────────────────────────────────
_VOID_TYPES = {"atrium", "courtyard", "void", "shaft", "lightwell", "cutout"}
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

    raw = []
    for obj in graph.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        d = obj.get("dimensions") or {}
        unit = d.get("unit")
        l = _to_m(d.get("length"), unit) or 0.4
        w = _to_m(d.get("width"), unit) or 0.4
        h = _to_m(d.get("height"), unit) or 0.4
        p = obj.get("position") or {}
        cx, cy, cz = float(p.get("x", 0) or 0), float(p.get("y", 0) or 0), float(p.get("z", 0) or 0)
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

    if interior:
        # Floor slab (top at y=0) + four tagged perimeter walls.
        solids.append(Solid("floor", "Floor", "floor", _TYPE_DEFAULT["floor"],
                            _box(room_l, 0.05, room_w, room_l / 2, -0.05, room_w / 2)))
        wc = _TYPE_DEFAULT["wall"]
        solids += [
            Solid("wall_-x", "Wall", "wall", wc, _box(_WALL_T, room_h, room_w, 0.0, 0.0, room_w / 2), side="-x"),
            Solid("wall_+x", "Wall", "wall", wc, _box(_WALL_T, room_h, room_w, room_l, 0.0, room_w / 2), side="+x"),
            Solid("wall_-z", "Wall", "wall", wc, _box(room_l, room_h, _WALL_T, room_l / 2, 0.0, 0.0), side="-z"),
            Solid("wall_+z", "Wall", "wall", wc, _box(room_l, room_h, _WALL_T, room_l / 2, 0.0, room_w), side="+z"),
        ]
    else:
        # Site-scale: a ground plane under the massing.
        cxz = _center_xz(body)
        span = _scene_span(body)
        solids.append(Solid("ground", "Ground", "ground", _TYPE_DEFAULT["ground"],
                            _box(2.4 * span, 0.05, 2.4 * span, cxz[0], -0.05, cxz[1])))

    for o, m in body:
        solids.append(Solid(
            id=str(o.get("id") or o.get("name") or "obj"),
            name=str(o.get("name") or o.get("type") or "object"),
            type=str(o.get("type") or "object"),
            color=_color_for(o, materials_by_key), manifold=m,
        ))

    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for s in solids:
        mesh = s.manifold.to_mesh()
        s.verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        s.tris = np.asarray(mesh.tri_verts, dtype=np.int64)
        if len(s.verts):
            lo = np.minimum(lo, s.verts.min(0))
            hi = np.maximum(hi, s.verts.max(0))
    kind = "interior" if interior else "exterior"
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
