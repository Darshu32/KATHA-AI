"""DXF exporter — AutoCAD-compatible 2D floor plan.

Uses ezdxf (R2010 format, universally readable). Emits a plan with
discrete layers so downstream users can toggle walls / openings /
furniture / dimensions independently.

Note: native DWG writing is proprietary and unreliable from pure Python.
DXF is the industry-accepted exchange format for this — open it in
AutoCAD/BricsCAD/DraftSight directly, or convert with ODA File Converter.
"""

from __future__ import annotations

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment

from app.knowledge import clearances


LAYERS = [
    ("WALLS", 7, "CONTINUOUS"),
    ("DOORS", 1, "CONTINUOUS"),
    ("WINDOWS", 4, "CONTINUOUS"),
    ("FURNITURE", 3, "CONTINUOUS"),
    ("MEP", 6, "DASHED"),
    ("ANNOTATIONS", 2, "CONTINUOUS"),
    ("DIMENSIONS", 2, "CONTINUOUS"),
]


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _layer_for(obj_type: str) -> str:
    t = (obj_type or "").lower()
    if t == "door":
        return "DOORS"
    if t in {"window", "bay_window"}:
        return "WINDOWS"
    if t in {"switch", "socket", "outlet", "light_fixture", "vent"}:
        return "MEP"
    return "FURNITURE"


def export(spec: dict, graph: dict) -> dict:
    doc = ezdxf.new(dxfversion="R2010", setup=True)
    for name, colour, ltype in LAYERS:
        layer = doc.layers.add(name=name) if name not in doc.layers else doc.layers.get(name)
        layer.color = colour
        try:
            layer.linetype = ltype
        except Exception:
            pass

    msp = doc.modelspace()

    meta = spec.get("meta", {})
    dims_m = meta.get("dimensions_m", {}) or {}
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    room_dims = room.get("dimensions") or dims_m
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    wall_t = 0.2  # metres

    # Outer + inner walls (two rectangles offset by wall thickness).
    _rect(msp, 0, 0, room_l, room_w, layer="WALLS")
    _rect(msp, wall_t, wall_t, room_l - wall_t, room_w - wall_t, layer="WALLS")

    # Objects.
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        pos = obj.get("position") or {}
        d = obj.get("dimensions") or {}
        cx = float(pos.get("x", 0))
        cz = float(pos.get("z", 0))
        l = _m(d.get("length")) or 0.4
        w = _m(d.get("width")) or 0.4
        layer = _layer_for(otype)
        _rect(msp, cx - l / 2, cz - w / 2, cx + l / 2, cz + w / 2, layer=layer)
        msp.add_text(
            otype.replace("_", " "),
            dxfattribs={"height": 0.12, "layer": "ANNOTATIONS"},
        ).set_placement((cx, cz), align=TextEntityAlignment.MIDDLE_CENTER)

    # Room overall dimension (bottom edge).
    try:
        dim = msp.add_linear_dim(
            base=(room_l / 2, -0.6),
            p1=(0, 0),
            p2=(room_l, 0),
            dimstyle="EZDXF",
            override={"dimtxt": 0.15},
        )
        dim.render()
        dim_v = msp.add_linear_dim(
            base=(-0.6, room_w / 2),
            p1=(0, 0),
            p2=(0, room_w),
            angle=90,
            dimstyle="EZDXF",
            override={"dimtxt": 0.15},
        )
        dim_v.render()
    except Exception:
        # ezdxf dimension API can fail on minimal templates; fallback text.
        msp.add_text(f"{room_l:.2f} m x {room_w:.2f} m",
                     dxfattribs={"height": 0.2, "layer": "DIMENSIONS"}
        ).set_placement((room_l / 2, -0.4), align=TextEntityAlignment.MIDDLE_CENTER)

    # Title block text.
    title = f"{meta.get('project_name','Untitled')} — {meta.get('theme','')}"
    msp.add_text(title, dxfattribs={"height": 0.25, "layer": "ANNOTATIONS"}).set_placement((0, room_w + 0.6))
    msp.add_text(
        f"Interior doors min {clearances.DOORS['interior']['width_mm'][0]}mm "
        f"| corridor min {clearances.CORRIDORS['residential']['min_width_mm']}mm",
        dxfattribs={"height": 0.15, "layer": "ANNOTATIONS"},
    ).set_placement((0, room_w + 0.3))

    # Write to bytes.
    stream = io.StringIO()
    doc.write(stream)
    data = stream.getvalue().encode("utf-8")

    return {
        "content_type": "application/dxf",
        "filename": f"{_safe_name(meta.get('project_name','project'))}-plan.dxf",
        "bytes": data,
    }


def _rect(msp, x1: float, y1: float, x2: float, y2: float, layer: str = "0") -> None:
    points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    msp.add_lwpolyline(points, close=True, dxfattribs={"layer": layer})


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
