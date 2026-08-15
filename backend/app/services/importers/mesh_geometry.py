"""Load a 3D model (OBJ / GLB / glTF / STL / PLY / OFF) into render-ready
geometry — Layer 5B, Tier 1 of upload→geometry.

Unlike the metadata importers (image/skp/… parse for the LLM manifest), this
pulls the ACTUAL geometry so an uploaded model flows into the kernel render
path: verts + tris → rasterizer → Nano Banana finish. No Manifold boolean is
needed — the software rasteriser draws triangles directly — so an arbitrary
(non-watertight) mesh renders fine.

Tier 1 does NOT reconstruct an editable parametric spec (no "move the wall",
no clean BIM) — that's Tier 2. Here the mesh is the geometry: we render it and
report its bounding dimensions.
"""

from __future__ import annotations

import io

import numpy as np

# Self-contained, single-file formats we can load from an upload. (A .gltf that
# references external .bin/textures won't resolve from one blob — .glb is the
# safe single-file glTF; we still accept .gltf for embedded-buffer files.)
_SUPPORTED = {".obj", ".glb", ".gltf", ".stl", ".ply", ".off"}


def supported_mesh_extensions() -> set[str]:
    return set(_SUPPORTED)


def _ext(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in (filename or "") else ""


def load_mesh(filename: str, payload: bytes, *, up_flip: bool = False) -> dict:
    """Parse a 3D model into render-ready geometry.

    Returns ``{verts (N,3) float32, tris (M,3) int32, dims (L,H,D) metres,
    units_known: bool, n_verts, n_tris, up_axis_flipped}``. The verts are
    recentred in x/z with the base dropped to y=0 (ready for the floor-aware
    camera); the model's own scale is preserved so glTF (metres) yields true
    dimensions. Raises ``ValueError`` on an unparseable / empty model.
    """
    ext = _ext(filename)
    if ext not in _SUPPORTED:
        raise ValueError(f"unsupported 3D format: {ext or '?'} "
                         f"(supported: {', '.join(sorted(_SUPPORTED))})")
    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover
        raise ValueError("trimesh is required to import 3D models") from exc

    try:
        # force='mesh' concatenates a scene graph (multiple parts + transforms)
        # into a single triangle mesh — exactly what the rasteriser wants.
        loaded = trimesh.load(io.BytesIO(payload), file_type=ext.lstrip("."), force="mesh")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not parse {ext} model: {exc}") from exc

    if loaded is None or not hasattr(loaded, "vertices") or len(loaded.vertices) == 0:
        raise ValueError("model contained no geometry")
    verts = np.asarray(loaded.vertices, dtype=np.float32)
    tris = np.asarray(getattr(loaded, "faces", []), dtype=np.int32)
    if tris.ndim != 2 or tris.shape[1] != 3 or len(tris) == 0:
        raise ValueError("model has no triangle faces (point cloud or curves only)")

    # Cheap integrity stats trimesh gives for free — surfaced on the spec sheet.
    watertight = bool(getattr(loaded, "is_watertight", False))
    try:
        volume = float(abs(loaded.volume)) if watertight else None
    except Exception:  # noqa: BLE001
        volume = None
    try:
        area = float(loaded.area)
    except Exception:  # noqa: BLE001
        area = None

    # Trust the file's Y-up (glTF standard) by default. The old always-on Z-up
    # flip mis-fired on wide-but-short shapes (a room-scale building or a low
    # table reads as "z-dominant" and would be tipped onto its side). Opt-in only.
    flipped = False
    if up_flip:
        verts, flipped = _to_y_up(verts)
    verts = _recentre_on_floor(verts)
    # Snap arbitrary model units (mm / cm / m …) to a sensible object scale so an
    # editable part reads as "0.85 m", not "85 m" (see _normalise_scale). Keep the
    # integrity stats consistent with the rescaled geometry.
    verts, unit_scale = _normalise_scale(verts)
    if unit_scale != 1.0:
        if volume is not None:
            volume *= unit_scale ** 3
        if area is not None:
            area *= unit_scale ** 2
    lo, hi = verts.min(0), verts.max(0)
    dims = (float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - lo[2]))  # L(x), H(y), D(z)
    return {
        "verts": verts, "tris": tris, "dims": dims,
        "units_known": ext in {".glb", ".gltf"},   # glTF is metres; OBJ/STL/PLY unitless
        "unit_scale": unit_scale,                   # power-of-10 applied to reach object scale
        "n_verts": int(len(verts)), "n_tris": int(len(tris)),
        "up_axis_flipped": flipped,
        "watertight": watertight, "volume": volume, "area": area,
    }


def _to_y_up(verts: np.ndarray) -> tuple[np.ndarray, bool]:
    """KATHA renders Y-up. Many CAD/SketchUp exports are Z-up; flip when the
    model is clearly Z-dominant (tall in z, not in y). Heuristic, Tier 1."""
    lo, hi = verts.min(0), verts.max(0)
    ext = hi - lo
    if ext[2] > 1.5 * ext[1] and ext[2] >= ext[0] * 0.5:
        v = verts[:, [0, 2, 1]].copy()   # y ← z
        v[:, 2] *= -1.0                   # preserve handedness
        return v.astype(np.float32), True
    return verts, False


def _recentre_on_floor(verts: np.ndarray) -> np.ndarray:
    """Centre the footprint on the origin (x,z) and drop the base to y=0, so the
    scene camera frames it and the object sits on the ground plane."""
    v = verts.astype(np.float32).copy()
    lo, hi = v.min(0), v.max(0)
    v[:, 0] -= (lo[0] + hi[0]) / 2.0
    v[:, 2] -= (lo[2] + hi[2]) / 2.0
    v[:, 1] -= lo[1]
    return v


def _normalise_scale(verts: np.ndarray) -> tuple[np.ndarray, float]:
    """Snap an arbitrarily-scaled model to a sensible object size by whole powers
    of 10 (a units guess: mm / cm / m). Geometry alone can't reveal the true unit,
    so if the largest dimension is outside the plausible object band we rescale by
    the nearest power of 10 that lands it inside — an "85 m" engine (authored in a
    large unit) becomes ~0.85 m. Uniform scale about the origin, so the floor
    (y=0) and centred footprint are preserved. Returns (verts, scale_applied);
    a model already in-band is returned unchanged (scale 1.0)."""
    from app.config import get_settings
    s = get_settings()
    lo_m, hi_m = float(s.import_scale_min_m), float(s.import_scale_max_m)
    lo, hi = verts.min(0), verts.max(0)
    maxd = float(np.max(hi - lo))
    if maxd <= 0 or not np.isfinite(maxd):
        return verts, 1.0
    scale = 1.0
    for _ in range(24):  # bounded — snap into [lo_m, hi_m] by powers of 10
        if maxd * scale > hi_m:
            scale /= 10.0
        elif maxd * scale < lo_m:
            scale *= 10.0
        else:
            break
    if scale != 1.0:
        verts = (verts * scale).astype(np.float32)
    return verts, scale


# ── Tier 2: decompose a mesh into editable PARTS ──────────────────────────────
def _part_type(dims: tuple[float, float, float]) -> str:
    """Coarse type from a part's proportions (Tier-2 v1 heuristic)."""
    length, height, depth = dims
    foot = max(length, depth, 1e-6)
    if height > 1.8 * foot and foot < 0.35:
        return "leg"                          # tall + thin footprint
    if height < 0.18 * foot:
        return "panel"                        # flat slab / top
    if height > 1.2 * foot:
        return "upright"                      # taller than wide (backrest / door)
    return "part"


def _sub_mesh(v: np.ndarray, comp_tris) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """A connected component's self-contained sub-mesh (local verts + reindexed
    tris) plus its bounding box (lo, hi)."""
    ct = np.asarray(comp_tris, np.int64)
    used = np.unique(ct)
    remap = {int(old): new for new, old in enumerate(used)}
    lv = v[used].astype(np.float32)
    lt = np.array([[remap[int(x)] for x in tri] for tri in ct], np.int32)
    return lv, lt, lv.min(0), lv.max(0)


def _part_from(pid: str, lv, lt, lo, hi, type_override: str | None = None) -> dict:
    dims = (float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - lo[2]))  # L,H,D
    return {
        "id": pid,
        "type": type_override or _part_type(dims),
        "position": {"x": float((lo[0] + hi[0]) / 2), "y": float(lo[1]),
                     "z": float((lo[2] + hi[2]) / 2)},           # bottom-centre
        "dimensions": {"length": dims[0], "width": dims[2], "height": dims[1]},
        "verts": lv,
        "tris": lt,
    }


def decompose_mesh(verts, tris, max_parts: int | None = None,
                   min_part_frac: float | None = None) -> list[dict]:
    """Split a mesh into editable PARTS = its connected components.

    Union-find over triangles' shared vertices (no graph-engine dependency, so it
    works where ``trimesh.split`` can't). Each component becomes a self-contained
    sub-mesh with a bounding box → position (bottom-centre) + dimensions + a coarse
    type. To stop a dense CAD model shattering into dozens of parts, only
    components at least ``min_part_frac`` of the largest (by bbox diagonal), up to
    ``max_parts``, are kept as individual editable parts; every smaller component
    merges into ONE "assembly" remainder part — so the render keeps all triangles
    but the editable list stays legible. Thresholds come from settings. A welded
    single-mesh model yields one part (true wall/room reconstruction is Tier 2b)."""
    from app.config import get_settings
    s = get_settings()
    if max_parts is None:
        max_parts = int(s.import_max_parts)
    if min_part_frac is None:
        min_part_frac = float(s.import_min_part_frac)

    v = np.asarray(verts, np.float32)
    t = np.asarray(tris, np.int64)
    if not len(t):
        return []

    parent = list(range(len(v)))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:      # path compression
            parent[x], x = root, parent[x]
        return root

    for tri in t:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        ra, rc = find(a), find(c)
        if ra != rc:
            parent[rc] = ra

    from collections import defaultdict
    groups: dict[int, list] = defaultdict(list)
    for tri in t:
        groups[find(int(tri[0]))].append(tri)

    # Build every component's sub-mesh + bbox, ranked by spatial size (diagonal).
    built = []
    for comp_tris in groups.values():
        lv, lt, lo, hi = _sub_mesh(v, comp_tris)
        built.append((float(np.linalg.norm(hi - lo)), lv, lt, lo, hi))
    built.sort(key=lambda b: b[0], reverse=True)
    biggest = built[0][0] if built else 0.0

    keep, rest = [], []
    for b in built:
        big_enough = biggest <= 0 or b[0] >= min_part_frac * biggest
        if big_enough and len(keep) < max(1, max_parts - 1):
            keep.append(b)
        else:
            rest.append(b)

    parts = [_part_from(f"part_{i}", lv, lt, lo, hi)
             for i, (_d, lv, lt, lo, hi) in enumerate(keep, 1)]

    # Merge the small / overflow components into one remainder part: no geometry is
    # dropped from the render, while the editable-part count stays bounded.
    if rest:
        vs, ts, off = [], [], 0
        for _d, lv, lt, _lo, _hi in rest:
            vs.append(lv)
            ts.append(lt + off)
            off += len(lv)
        mv = np.concatenate(vs).astype(np.float32)
        mt = np.concatenate(ts).astype(np.int32)
        parts.append(_part_from(f"part_{len(keep) + 1}", mv, mt, mv.min(0), mv.max(0),
                                type_override="assembly"))
    return parts


def slice_to_plan_image(verts, tris, at_y: float | None = None,
                        size: int = 1000, line: int = 6) -> bytes | None:
    """Tier 2b — horizontal cut of a building mesh at height ``at_y`` → a floor-
    plan image: the wall lines where the mesh crosses the plane, rasterised
    black-on-white. That plan then feeds the floor-plan → rooms vision pipeline.

    Dependency-free triangle-plane intersection. Returns None when the cut is
    empty (not a building model, or wrong height)."""
    v = np.asarray(verts, np.float32)
    t = np.asarray(tris, np.int64)
    if not len(t):
        return None
    lo, hi = v.min(0), v.max(0)
    if at_y is None:
        at_y = float(lo[1] + (hi[1] - lo[1]) * 0.4)      # ~standard plan-cut height

    segs: list = []
    for tri in t:
        p = v[tri]                                        # (3,3)
        above = p[:, 1] > at_y
        if above.all() or not above.any():
            continue                                      # triangle doesn't cross the plane
        pts = []
        for i in range(3):
            a, b = p[i], p[(i + 1) % 3]
            if (a[1] > at_y) != (b[1] > at_y):
                s = (at_y - a[1]) / (b[1] - a[1])
                pts.append((float(a[0] + s * (b[0] - a[0])), float(a[2] + s * (b[2] - a[2]))))
        if len(pts) >= 2:
            segs.append((pts[0], pts[1]))
    if not segs:
        return None

    import io
    from PIL import Image, ImageDraw
    xs = [q[0] for s in segs for q in s]
    zs = [q[1] for s in segs for q in s]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    w, h = (maxx - minx) or 1.0, (maxz - minz) or 1.0
    m = 48.0
    sc = min((size - 2 * m) / w, (size - 2 * m) / h)
    im = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(im)

    def px(q):
        return (m + (q[0] - minx) * sc, m + (q[1] - minz) * sc)

    for a, b in segs:
        d.line([px(a), px(b)], fill="black", width=line)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
