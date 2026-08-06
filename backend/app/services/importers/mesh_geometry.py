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


def load_mesh(filename: str, payload: bytes) -> dict:
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

    verts, flipped = _to_y_up(verts)
    verts = _recentre_on_floor(verts)
    lo, hi = verts.min(0), verts.max(0)
    dims = (float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - lo[2]))  # L(x), H(y), D(z)
    return {
        "verts": verts, "tris": tris, "dims": dims,
        "units_known": ext in {".glb", ".gltf"},   # glTF is metres; OBJ/STL/PLY unitless
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
