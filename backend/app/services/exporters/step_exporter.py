"""STEP AP214 exporter — ISO-10303 faceted BREP.

Hand-written minimal STEP file. Each design object becomes a MANIFOLD_SOLID_BREP
made of 6 ADVANCED_FACEs (polygonal). No NURBS, no tolerances — intentionally
simple so the output is deterministic and parseable by FreeCAD, Fusion 360,
SolidWorks, OnShape, Siemens NX.

Written against ISO-10303-21 syntax and the AP214 automotive design schema
(widely supported). If you need AP242, rename the schema line — the rest is
identical for faceted BREP.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


class _StepBuilder:
    def __init__(self):
        self._id = 0
        self.lines: list[str] = []

    def add(self, entity: str) -> int:
        self._id += 1
        self.lines.append(f"#{self._id}={entity};")
        return self._id

    def render(self) -> list[str]:
        return list(self.lines)


def _point(b: _StepBuilder, x: float, y: float, z: float) -> int:
    return b.add(f"CARTESIAN_POINT('',({x:.6f},{y:.6f},{z:.6f}))")


def _direction(b: _StepBuilder, x: float, y: float, z: float) -> int:
    return b.add(f"DIRECTION('',({x:.6f},{y:.6f},{z:.6f}))")


def _axis2_placement(b: _StepBuilder, origin_id: int, z_dir_id: int, x_dir_id: int) -> int:
    return b.add(f"AXIS2_PLACEMENT_3D('',#{origin_id},#{z_dir_id},#{x_dir_id})")


def _vertex(b: _StepBuilder, point_id: int) -> int:
    return b.add(f"VERTEX_POINT('',#{point_id})")


def _line(b: _StepBuilder, point_id: int, dir_id: int) -> int:
    vec = b.add(f"VECTOR('',#{dir_id},1.0)")
    return b.add(f"LINE('',#{point_id},#{vec})")


def _edge_curve(b: _StepBuilder, v1: int, v2: int, line_id: int) -> int:
    return b.add(f"EDGE_CURVE('',#{v1},#{v2},#{line_id},.T.)")


def _oriented_edge(b: _StepBuilder, edge: int, same_sense: bool) -> int:
    s = ".T." if same_sense else ".F."
    return b.add(f"ORIENTED_EDGE('',*,*,#{edge},{s})")


def _edge_loop(b: _StepBuilder, oriented_edges: list[int]) -> int:
    refs = ",".join(f"#{eid}" for eid in oriented_edges)
    return b.add(f"EDGE_LOOP('',({refs}))")


def _face_bound(b: _StepBuilder, loop_id: int) -> int:
    return b.add(f"FACE_OUTER_BOUND('',#{loop_id},.T.)")


def _plane(b: _StepBuilder, axis_placement_id: int) -> int:
    return b.add(f"PLANE('',#{axis_placement_id})")


def _advanced_face(b: _StepBuilder, bound: int, plane: int) -> int:
    return b.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)")


def _emit_box_brep(b: _StepBuilder, ox: float, oy: float, oz: float, lx: float, ly: float, lz: float, name: str) -> int:
    """Emit a manifold solid BREP for an axis-aligned box. Returns manifold id."""
    # 8 corners.
    corners = [
        (ox,     oy,     oz),
        (ox+lx,  oy,     oz),
        (ox+lx,  oy+ly,  oz),
        (ox,     oy+ly,  oz),
        (ox,     oy,     oz+lz),
        (ox+lx,  oy,     oz+lz),
        (ox+lx,  oy+ly,  oz+lz),
        (ox,     oy+ly,  oz+lz),
    ]
    pts = [_point(b, *c) for c in corners]
    verts = [_vertex(b, p) for p in pts]

    # Direction helpers.
    dir_x = _direction(b, 1, 0, 0)
    dir_y = _direction(b, 0, 1, 0)
    dir_z = _direction(b, 0, 0, 1)
    dir_nx = _direction(b, -1, 0, 0)
    dir_ny = _direction(b, 0, -1, 0)
    dir_nz = _direction(b, 0, 0, -1)

    # 12 edges indexed by corner pairs.
    edges: dict[tuple[int, int], int] = {}

    def edge_between(a: int, c: int) -> int:
        key = (a, c)
        if key in edges:
            return edges[key]
        p_a, p_c = corners[a], corners[c]
        dx, dy, dz = p_c[0] - p_a[0], p_c[1] - p_a[1], p_c[2] - p_a[2]
        length = max((dx * dx + dy * dy + dz * dz) ** 0.5, 1e-9)
        ndir = _direction(b, dx / length, dy / length, dz / length)
        line_id = _line(b, pts[a], ndir)
        edges[key] = _edge_curve(b, verts[a], verts[c], line_id)
        return edges[key]

    # 6 faces with CCW outward-normal loops.
    face_defs = [
        # (loop corner indices in order, normal direction, in-plane x direction)
        ([0, 3, 2, 1], dir_nz, dir_x),   # bottom z-
        ([4, 5, 6, 7], dir_z,  dir_x),   # top z+
        ([0, 1, 5, 4], dir_ny, dir_x),   # front y-
        ([2, 3, 7, 6], dir_y,  dir_nx),  # back y+
        ([0, 4, 7, 3], dir_nx, dir_ny),  # left x-
        ([1, 2, 6, 5], dir_x,  dir_y),   # right x+
    ]
    faces = []
    for corners_idx, normal_dir, in_plane_x in face_defs:
        # Oriented edges around the loop.
        oeds = []
        for i in range(4):
            a = corners_idx[i]
            c = corners_idx[(i + 1) % 4]
            canonical = (min(a, c), max(a, c))
            eid = edges.get(canonical)
            if eid is None:
                eid = edge_between(canonical[0], canonical[1])
            oeds.append(_oriented_edge(b, eid, same_sense=(a < c)))
        loop = _edge_loop(b, oeds)
        bound = _face_bound(b, loop)

        # Plane sits at the first corner of the loop with the face normal.
        origin = pts[corners_idx[0]]
        placement = _axis2_placement(b, origin, normal_dir, in_plane_x)
        plane = _plane(b, placement)
        faces.append(_advanced_face(b, bound, plane))

    shell = b.add(f"CLOSED_SHELL('',({','.join(f'#{f}' for f in faces)}))")
    return b.add(f"MANIFOLD_SOLID_BREP('{name}',#{shell})")


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"

    b = _StepBuilder()

    # Global context: length unit = metre, plane angle = radian.
    origin = _point(b, 0, 0, 0)
    dz = _direction(b, 0, 0, 1)
    dx = _direction(b, 1, 0, 0)
    world_placement = _axis2_placement(b, origin, dz, dx)

    length_unit = b.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    plane_unit = b.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    solid_unit = b.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    epsilon = b.add(
        f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.001),#{length_unit},'distance_accuracy','')"
    )
    ctx = b.add(
        f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{epsilon}))"
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length_unit},#{plane_unit},#{solid_unit}))"
        f"REPRESENTATION_CONTEXT('Context #1','3D Context'))"
    )

    # Emit one BREP per object (plus room floor).
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0) * 1000.0
    room_w = float(room_dims.get("width") or 5.0) * 1000.0
    # STEP uses mm here so multiply.

    breps: list[int] = []
    breps.append(_emit_box_brep(b, 0, 0, -20, room_l, room_w, 20, "Floor"))

    for obj in graph.get("objects", []):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l = max(_m(d.get("length")) or 0.4, 0.05) * 1000.0
        w = max(_m(d.get("width")) or 0.4, 0.05) * 1000.0
        h = max(_m(d.get("height")) or 0.4, 0.05) * 1000.0
        cx = float(pos.get("x", 0)) * 1000.0
        cy = float(pos.get("z", 0)) * 1000.0
        cz = float(pos.get("y", 0) or 0) * 1000.0
        name = (obj.get("id") or obj.get("type") or "object").replace("'", "")
        breps.append(_emit_box_brep(b, cx - l / 2, cy - w / 2, cz, l, w, h, name))

    # Shape representation linking all BREPs to the context.
    shape_rep = b.add(
        f"SHAPE_REPRESENTATION('',({','.join(f'#{x}' for x in [world_placement] + breps)}),#{ctx})"
    )

    app_context_text = (
        "APPLICATION_CONTEXT('core data for automotive mechanical design processes')"
    )
    app_context = b.add(app_context_text)
    product_context = b.add(
        f"PRODUCT_CONTEXT('',#{app_context},'mechanical')"
    )
    safe_name = _safe_name(project_name)
    product = b.add(
        f"PRODUCT('{safe_name}','{project_name}','',(#{product_context}))"
    )
    # Bind product definition to shape representation (minimal chain for AP214 viewers).
    pdef_formation = b.add(f"PRODUCT_DEFINITION_FORMATION('','',#{product})")
    pdef_context = b.add(
        f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app_context},'design')"
    )
    pd = b.add(
        f"PRODUCT_DEFINITION('design','',#{pdef_formation},#{pdef_context})"
    )
    pds = b.add(f"PRODUCT_DEFINITION_SHAPE('',$,#{pd})")
    b.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{shape_rep})")

    # Compose file.
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        f"FILE_DESCRIPTION(('KATHA AI faceted BREP'),'2;1');",
        f"FILE_NAME('{_safe_name(project_name)}.step','{timestamp}',('KATHA AI'),(''),'KATHA STEP exporter','',' ');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));",
        "ENDSEC;",
        "DATA;",
    ]
    footer = ["ENDSEC;", "END-ISO-10303-21;"]
    payload = "\n".join(header + b.render() + footer).encode("ascii", errors="replace")

    return {
        "content_type": "application/x-step",
        "filename": f"{_safe_name(project_name)}-cad.step",
        "bytes": payload,
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
