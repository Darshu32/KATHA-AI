"""Rhino .3dm exporter — closes the import/edit/export round-trip.

Architects using Rhino expect KATHA to read .3dm *and* hand it back as
.3dm once we've thought about the design. Without an exporter the
universal-OS pitch stops at "Import from any software"; with one we
can complete "Think and design in KATHA AI. Export to every tool."

We use rhino3dm — McNeel's official MIT-licensed Python binding to the
openNURBS kernel. The same library the importer uses, so the file we
write is the same shape Rhino itself produces. Output is a Rhino-7
archive (m.Write(path, 7)); Rhino 7 and 8 open it natively.

Layer scheme:
  · "Room"           — floor slab + space boundary
  · One per material — so the architect can isolate by material in
                       Rhino with a single click
  · "Furnishings"    — fallback bucket for objects that don't name a
                       known material

Each design object becomes a Brep solid via Brep.CreateFromBox over the
object's AABB. Boxes are axis-aligned because the KATHA design graph
carries dimensions + position but no rotation matrix in v1; rotations
can be re-added once the upstream graph carries them.

Coordinate convention: KATHA graph is Y-up (height), Z-depth.
Rhino is Z-up by convention. We swap on the way out (KATHA y → Rhino z,
KATHA z → Rhino y), matching what ifc_exporter does on the same axes.

Dimensions: object dims arrive in metres OR millimetres depending on
upstream; the same _m() coercion the OBJ exporter uses applies
(values > 20 are treated as mm).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

try:
    import rhino3dm
except Exception:  # noqa: BLE001
    rhino3dm = None


def _m(value: Any) -> float:
    """Coerce a length to metres. Values > 20 are treated as mm
    (matches the OBJ / IFC exporters' convention)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _safe_name(name: str) -> str:
    return (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-")
        or "project"
    )


def _make_layer(model, name: str, color: tuple[int, int, int] | None = None) -> int:
    layer = rhino3dm.Layer()
    layer.Name = name
    if color is not None:
        try:
            layer.Color = (color[0], color[1], color[2], 255)
        except Exception:  # noqa: BLE001
            pass
    return model.Layers.Add(layer)


def _hex_to_rgb(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    v = value.lstrip("#")
    if len(v) != 6:
        return None
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return None


def _add_box(model, name: str, layer_idx: int, min_pt, max_pt) -> None:
    bbox = rhino3dm.BoundingBox(min_pt, max_pt)
    brep = rhino3dm.Brep.CreateFromBox(rhino3dm.Box(bbox))
    if brep is None:
        return
    attrs = rhino3dm.ObjectAttributes()
    attrs.Name = name
    attrs.LayerIndex = layer_idx
    model.Objects.AddBrep(brep, attrs)


def export(spec: dict, graph: dict) -> dict:
    if rhino3dm is None:
        raise RuntimeError("rhino3dm is not installed; cannot export .3dm")

    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"

    model = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    model.Settings.ModelAbsoluteTolerance = 0.001

    # ── Layers ────────────────────────────────────────────────────
    room_layer_idx = _make_layer(model, "Room", (200, 195, 180))

    # One layer per known material. Map by material id (or name).
    layer_for_material: dict[str, int] = {}
    for mat in graph.get("materials") or []:
        mid = mat.get("id") or mat.get("name")
        if not mid or mid in layer_for_material:
            continue
        layer_name = mat.get("name") or mid
        layer_for_material[mid] = _make_layer(
            model, str(layer_name), _hex_to_rgb(mat.get("color"))
        )

    fallback_idx = _make_layer(model, "Furnishings", (170, 170, 170))

    # ── Room (floor slab) ─────────────────────────────────────────
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    room_dims = room.get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    # room_h is unused here — kept for potential future wall geometry.
    _ = float(room_dims.get("height") or 3.0)

    _add_box(
        model,
        "Floor",
        room_layer_idx,
        rhino3dm.Point3d(0.0, 0.0, -0.02),
        rhino3dm.Point3d(room_l, room_w, 0.0),
    )

    # ── Furnishings ───────────────────────────────────────────────
    for obj in graph.get("objects") or []:
        otype = (obj.get("type") or "object").lower()
        oid = str(obj.get("id") or otype)
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}

        # KATHA y-up → Rhino z-up axis swap (matches ifc_exporter).
        cx = float(pos.get("x", 0))
        cy = float(pos.get("z", 0))
        cz = float(pos.get("y", 0) or 0)

        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)

        mat_ref = obj.get("material")
        layer_idx = layer_for_material.get(mat_ref, fallback_idx) if mat_ref else fallback_idx

        _add_box(
            model,
            oid,
            layer_idx,
            rhino3dm.Point3d(cx - l / 2, cy - w / 2, cz),
            rhino3dm.Point3d(cx + l / 2, cy + w / 2, cz + h),
        )

    # Write to a temp file (rhino3dm only writes via paths), then read back.
    with tempfile.NamedTemporaryFile("wb", suffix=".3dm", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        if not model.Write(tmp_path, 7):
            raise RuntimeError("rhino3dm File3dm.Write returned false")
        data = Path(tmp_path).read_bytes()
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    return {
        "content_type": "application/octet-stream",
        "filename": f"{_safe_name(project_name)}-model.3dm",
        "bytes": data,
    }
