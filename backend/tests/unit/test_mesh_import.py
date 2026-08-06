"""3D-model import (Layer 5B, Tier 1: upload → geometry).

An uploaded OBJ/GLB must parse into render-ready (verts, tris) with correct
overall dimensions, recentred on the floor, and flow through the rasteriser to
a clay render — no Manifold, no spec reconstruction. The finish pass (network)
is NOT exercised here (finish=False)."""

from __future__ import annotations

import pytest
import trimesh

from app.services.importers.mesh_geometry import load_mesh, supported_mesh_extensions
from app.services.spatial.render_pipeline import render_mesh


def _chair_obj_glb() -> tuple[bytes, bytes]:
    def box(ext, c):
        return trimesh.creation.box(extents=ext, transform=trimesh.transformations.translation_matrix(c))
    parts = [
        box((0.6, 0.05, 0.6), (0, 0.425, 0)),         # seat
        box((0.05, 0.4, 0.05), (0.27, 0.2, 0.27)),    # 4 legs
        box((0.05, 0.4, 0.05), (-0.27, 0.2, 0.27)),
        box((0.05, 0.4, 0.05), (0.27, 0.2, -0.27)),
        box((0.05, 0.4, 0.05), (-0.27, 0.2, -0.27)),
        box((0.6, 0.45, 0.05), (0, 0.675, -0.27)),    # backrest
    ]
    m = trimesh.util.concatenate(parts)
    return m.export(file_type="obj").encode(), m.export(file_type="glb")


def test_load_obj_geometry_dims_and_floor():
    obj, _ = _chair_obj_glb()
    g = load_mesh("chair.obj", obj)
    assert g["n_verts"] == 48 and g["n_tris"] == 72
    length, height, depth = g["dims"]
    assert (round(length, 2), round(height, 2), round(depth, 2)) == (0.6, 0.9, 0.6)
    assert g["units_known"] is False                       # OBJ is unitless
    assert abs(float(g["verts"][:, 1].min())) < 1e-4       # base dropped to y=0
    assert g["tris"].shape[1] == 3


def test_load_glb_units_known():
    _, glb = _chair_obj_glb()
    g = load_mesh("chair.glb", glb)
    assert g["units_known"] is True                        # glTF is metres
    assert round(g["dims"][1], 2) == 0.9


def test_unsupported_and_garbage_raise():
    with pytest.raises(ValueError):
        load_mesh("model.dwg", b"anything")                # unsupported extension
    with pytest.raises(ValueError):
        load_mesh("model.obj", b"this is not an obj file") # no geometry
    assert {".obj", ".glb", ".stl"} <= supported_mesh_extensions()


async def test_render_mesh_produces_clay_png():
    obj, _ = _chair_obj_glb()
    g = load_mesh("chair.obj", obj)
    rr = await render_mesh(g["verts"], g["tris"], finish=False)          # no network
    assert rr is not None
    assert rr.finished is False and rr.kind == "product"   # 0.9 m longest → object scale
    assert rr.base_bytes[:8] == b"\x89PNG\r\n\x1a\n"        # real PNG
    assert rr.hotspots                                     # the model projects a hotspot


def test_silhouette_unions_to_real_outline():
    from app.services.spatial.drawings2d import _silhouette
    obj, _ = _chair_obj_glb()
    g = load_mesh("chair.obj", obj)
    rings = _silhouette(g["verts"], g["tris"], (2, 1))     # side elevation
    assert rings and all(r.shape[1] == 2 for r in rings)
    assert max(len(r) for r in rings) > 4                  # not the 4-pt bbox fallback


def test_decompose_mesh_splits_connected_components():
    from app.services.importers.mesh_geometry import decompose_mesh
    obj, _ = _chair_obj_glb()                         # 6 disjoint boxes
    g = load_mesh("chair.obj", obj)
    parts = decompose_mesh(g["verts"], g["tris"])
    assert len(parts) == 6                            # seat + 4 legs + backrest
    assert sum(1 for p in parts if p["type"] == "leg") == 4
    for p in parts:                                   # each part is self-contained
        assert int(p["tris"].max()) < len(p["verts"])
        assert p["dimensions"]["height"] > 0


def test_reconstruct_builds_editable_part_graph():
    from app.services.mesh_reconstruct import reconstruct_from_mesh
    obj, _ = _chair_obj_glb()
    g = load_mesh("chair.obj", obj)
    graph, parts = reconstruct_from_mesh(g["verts"], g["tris"], "p1", "walnut")
    assert len(parts) == 6
    assert graph["design_type"] == "product"          # object scale
    assert len(graph["objects"]) == 6
    assert all(o["role"] == "imported_part" for o in graph["objects"])
    assert all("position" in o and "dimensions" in o for o in graph["objects"])


def test_slice_to_plan_image_from_building():
    from app.services.importers.mesh_geometry import slice_to_plan_image

    def box(e, c):
        return trimesh.creation.box(extents=e, transform=trimesh.transformations.translation_matrix(c))
    walls = [box((8, 2.8, 0.15), (4, 1.4, 0.075)), box((8, 2.8, 0.15), (4, 1.4, 5.925)),
             box((0.15, 2.8, 6), (0.075, 1.4, 3)), box((0.15, 2.8, 6), (7.925, 1.4, 3)),
             box((0.15, 2.8, 6), (4, 1.4, 3))]
    g = load_mesh("building.glb", trimesh.util.concatenate(walls).export(file_type="glb"))
    png = slice_to_plan_image(g["verts"], g["tris"])       # horizontal plan-cut
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_slice_returns_none_for_flat_mesh():
    import numpy as np

    from app.services.importers.mesh_geometry import slice_to_plan_image
    verts = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32)  # flat at y=0
    tris = np.array([[0, 1, 2], [0, 2, 3]], np.int32)
    assert slice_to_plan_image(verts, tris, at_y=0.5) is None   # nothing crosses the cut


def test_mesh_spec_sheet_svg_wellformed_and_small():
    import xml.dom.minidom as minidom

    from app.services.spatial.drawings2d import mesh_spec_sheet_svg
    obj, _ = _chair_obj_glb()
    g = load_mesh("chair.obj", obj)
    meta = {"filename": "chair.obj", "units_known": False, "n_tris": g["n_tris"],
            "n_verts": g["n_verts"], "watertight": g["watertight"],
            "volume": g["volume"], "area": g["area"]}
    svg = mesh_spec_sheet_svg(g["verts"], g["tris"], meta)
    minidom.parseString(svg)                               # well-formed XML
    for token in ("FRONT", "SIDE", "TOP", "OVERALL", "MODEL", "Watertight",
                  "IMPORTED 3D MODEL", "chair.obj"):
        assert token in svg, token
    assert len(svg) < 60000                                # silhouette union keeps it tiny
