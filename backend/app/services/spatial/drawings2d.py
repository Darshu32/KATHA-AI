"""Geometry-true 2D drawings + sheet composition, from the real kernel solids.

Unlike the graph-projected views, these are cut and projected from the actual
Manifold geometry, so a section shows walls *with their openings* and the
furniture profiles the cut passes through — true to the 3D model.

KATHA axes: x = length, y = height (up), z = depth.
  elevation  = project()            → x–y silhouette (depth dropped)
  section    = (solid ∩ z-slab).project()          → x–y cut profile at a z
  plan       = rotate y→z, then (solid ∩ slab).project() → x–(−z) at a height

Output is self-contained SVG in the KATHA drafting style; ``sheet_svg`` lays the
three views onto one titled sheet (title block, scale bar, north arrow).
"""

from __future__ import annotations

from manifold3d import Manifold

from app.services.spatial.code_checks import code_label, run_code_checks, tally
from app.services.spatial.kernel import build_scene

_INK = "#1A1A1A"
_PENCIL = "#C8362D"
_POCHE = "#d9d6d0"
_HAIR = "#e5e2dc"
_MUTE = "#9a9a95"
_STRUCT = {"ground"}

Poly = list[tuple[float, float]]


def _polys_of(cross) -> list[Poly]:
    try:
        return [[(float(p[0]), float(p[1])) for p in poly] for poly in cross.to_polygons()]
    except Exception:  # noqa: BLE001
        return []


def _slab_z(at: float, span: float) -> Manifold:
    t, big = 0.02, span * 3
    return Manifold.cube((big, big, t), False).translate((-span, -span, at - t / 2))


def _span(bbox: tuple) -> float:
    return float(max(bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2], 1.0))


# ── per-view geometry (returns cut polys, outline polys, subtitle) ────────────
def _elevation_data(graph: dict) -> tuple[list[Poly], list[Poly], str]:
    solids, _bbox, _kind = build_scene(graph)
    outline: list[Poly] = []
    for s in solids:
        if s.type in _STRUCT:
            continue
        try:
            outline += _polys_of(s.manifold.project())
        except Exception:  # noqa: BLE001
            continue
    return [], outline, "orthographic"


def _section_data(graph: dict, at_z: float | None) -> tuple[list[Poly], list[Poly], str]:
    solids, bbox, _kind = build_scene(graph)
    span = _span(bbox)
    z = at_z if at_z is not None else (bbox[2] + bbox[5]) / 2.0
    slab = _slab_z(z, span)
    cut: list[Poly] = []
    outline: list[Poly] = []
    for s in solids:
        if s.type in _STRUCT:
            continue
        try:
            outline += _polys_of(s.manifold.project())
            inter = s.manifold ^ slab
            if inter.volume() >= 1e-7:
                cut += _polys_of(inter.project())
        except Exception:  # noqa: BLE001
            continue
    return cut, outline, f"cut z = {z:.2f} m"


def _plan_data(graph: dict, at_y: float = 1.2) -> tuple[list[Poly], list[Poly], str]:
    solids, bbox, _kind = build_scene(graph)
    span = _span(bbox)
    slab = _slab_z(at_y, span)  # after rotating y→z, cut at (old) y = at_y
    cut: list[Poly] = []
    outline: list[Poly] = []
    for s in solids:
        if s.type in _STRUCT:
            continue
        try:
            m = s.manifold.rotate((90.0, 0.0, 0.0))  # KATHA-y → Manifold-z
            outline += _polys_of(m.project())
            inter = m ^ slab
            if inter.volume() >= 1e-7:
                cut += _polys_of(inter.project())
        except Exception:  # noqa: BLE001
            continue
    return cut, outline, f"cut {at_y:.2f} m"


# ── product (single-object) views + schedule ──────────────────────────────────
def _side_data(graph: dict) -> tuple[list[Poly], list[Poly], str]:
    """Side elevation — rotate z→x (90° about y), then project → z–y silhouette."""
    solids, _bbox, _kind = build_scene(graph)
    outline: list[Poly] = []
    for s in solids:
        if s.type in _STRUCT:
            continue
        try:
            outline += _polys_of(s.manifold.rotate((0.0, 90.0, 0.0)).project())
        except Exception:  # noqa: BLE001
            continue
    return [], outline, "orthographic"


def _top_data(graph: dict) -> tuple[list[Poly], list[Poly], str]:
    """Top view — rotate y→z (90° about x), then project → the x–z footprint."""
    solids, _bbox, _kind = build_scene(graph)
    outline: list[Poly] = []
    for s in solids:
        if s.type in _STRUCT:
            continue
        try:
            outline += _polys_of(s.manifold.rotate((90.0, 0.0, 0.0)).project())
        except Exception:  # noqa: BLE001
            continue
    return [], outline, "orthographic"


def _mm(v) -> float:
    """Coerce a graph dimension to millimetres (product parts are authored in m)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f * 1000.0 if 0 < f <= 20 else f


def _overall_dims_m(graph: dict) -> tuple[float, float, float]:
    """(length x, depth z, height y) of the object in metres, ground excluded."""
    import numpy as np

    solids, _bbox, _kind = build_scene(graph)
    chunks = [s.verts for s in solids
              if s.type not in _STRUCT and s.verts is not None and len(s.verts)]
    if not chunks:
        return 0.0, 0.0, 0.0
    v = np.vstack(chunks)
    lo, hi = v.min(0), v.max(0)
    return float(hi[0] - lo[0]), float(hi[2] - lo[2]), float(hi[1] - lo[1])


def _bom_rows(graph: dict) -> list[dict]:
    """Parts schedule from the product parts — identical parts folded to a qty."""
    from collections import OrderedDict

    agg: "OrderedDict[tuple, int]" = OrderedDict()
    for o in graph.get("objects") or []:
        if not isinstance(o, dict):
            continue
        d = o.get("dimensions") or {}
        key = (
            str(o.get("type") or o.get("id") or "part").replace("_", " "),
            round(_mm(d.get("length"))), round(_mm(d.get("width"))), round(_mm(d.get("height"))),
            str(o.get("material") or "—").replace("_", " "),
        )
        agg[key] = agg.get(key, 0) + 1
    rows: list[dict] = []
    for i, ((part, length, width, height, mat), qty) in enumerate(agg.items(), 1):
        rows.append({"tag": f"P{i:02d}", "part": part,
                     "size": f"{length}×{width}×{height}", "material": mat, "qty": qty})
    return rows


# ── rendering ─────────────────────────────────────────────────────────────────
def _bounds(polys: list[Poly]):
    pts = [p for poly in polys for p in poly]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _panel(cut: list[Poly], outline: list[Poly], bx: float, by: float, bw: float, bh: float,
           title: str, sub: str) -> tuple[str, float]:
    """Render one view into the box (bx,by,bw,bh). Returns (svg, metres_per_px)."""
    frame = (f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" stroke="{_HAIR}" stroke-width="1"/>'
             f'<text x="{bx + 12}" y="{by + 20}" fill="{_INK}" font-size="14" font-weight="700" letter-spacing="1.5">{title}</text>'
             f'<text x="{bx + bw - 12}" y="{by + 20}" text-anchor="end" fill="{_MUTE}" font-size="11">{sub}</text>')
    allp = cut + outline
    if not allp:
        return frame + f'<text x="{bx + bw / 2}" y="{by + bh / 2}" text-anchor="middle" fill="{_MUTE}" font-size="12">no geometry</text>', 0.0
    minx, miny, maxx, maxy = _bounds(allp)
    w, h = (maxx - minx) or 1, (maxy - miny) or 1
    m, top = 26.0, 34.0
    iw, ih = bw - 2 * m, bh - m - top
    sc = min(iw / w, ih / h)
    ox = bx + m + (iw - w * sc) / 2
    oy = by + top + (ih - h * sc) / 2

    def pt(p):
        return f"{ox + (p[0] - minx) * sc:.1f},{oy + (maxy - p[1]) * sc:.1f}"

    def path(polys):
        return " ".join("M" + " L".join(pt(p) for p in poly) + " Z" for poly in polys if len(poly) >= 3)

    body = frame
    if outline:
        body += f'<path d="{path(outline)}" fill="none" stroke="#b9b6b0" stroke-width="1" fill-rule="evenodd"/>'
    if cut:
        body += (f'<path d="{path(cut)}" fill="{_POCHE}" stroke="{_INK}" stroke-width="2" '
                 f'fill-rule="evenodd" stroke-linejoin="round"/>')
    return body, (1.0 / sc if sc else 0.0)


def _scale_bar(x: float, y: float, m_per_px: float) -> str:
    if m_per_px <= 0:
        return ""
    seg_px = 1.0 / m_per_px  # 1 metre
    n = 4
    parts = [f'<text x="{x}" y="{y - 6}" fill="{_MUTE}" font-size="9" letter-spacing="1">0        {n} m</text>']
    for i in range(n):
        fill = _INK if i % 2 == 0 else "#FFFFFF"
        parts.append(f'<rect x="{x + i * seg_px:.1f}" y="{y}" width="{seg_px:.1f}" height="5" '
                     f'fill="{fill}" stroke="{_INK}" stroke-width="0.6"/>')
    return "".join(parts)


def _north(x: float, y: float) -> str:
    return (f'<g stroke="{_INK}" stroke-width="1.2" fill="{_INK}">'
            f'<line x1="{x}" y1="{y + 16}" x2="{x}" y2="{y - 16}"/>'
            f'<path d="M{x - 4},{y - 8} L{x},{y - 18} L{x + 4},{y - 8} Z"/>'
            f'<text x="{x}" y="{y + 30}" text-anchor="middle" font-size="10" font-weight="700" stroke="none">N</text></g>')


def _wrap(body: str, w: float, h: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'font-family="ui-monospace,monospace"><rect width="{w:.0f}" height="{h:.0f}" fill="#FFFFFF"/>'
            f'{body}</svg>')


def _single(cut, outline, title, sub) -> str:
    W, H = 1000.0, 720.0
    body, _ = _panel(cut, outline, 20, 20, W - 40, H - 40, title, sub)
    return _wrap(body, W, H)


def section_svg(graph: dict, at_z: float | None = None) -> str:
    return _single(*_section_data(graph, at_z), "SECTION")


def elevation_svg(graph: dict) -> str:
    return _single(*_elevation_data(graph), "ELEVATION")


def plan_svg(graph: dict, at_y: float = 1.2) -> str:
    return _single(*_plan_data(graph, at_y), "PLAN")


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_product(graph: dict) -> bool:
    return str(graph.get("design_type") or "").lower() == "product"


def _product_type(graph: dict) -> str:
    """The whole-object type ("dining_table") for the titleblock — from a raw
    ``product`` dict if present, else the ``product_type`` constraint the
    orchestrator stamps, else the coarse design_type."""
    prod = graph.get("product")
    if isinstance(prod, dict) and prod.get("type"):
        return str(prod["type"])
    for c in graph.get("constraints") or []:
        if isinstance(c, dict) and c.get("id") == "product_type" and c.get("value"):
            return str(c["value"])
    return str(graph.get("design_type") or "product")


def _schedule_panel(bx: float, by: float, bw: float, bh: float, rows: list[dict]) -> str:
    """The parts schedule (bill of materials) as a ruled table."""
    out = (f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" stroke="{_HAIR}" stroke-width="1"/>'
           f'<text x="{bx + 12}" y="{by + 22}" fill="{_INK}" font-size="14" font-weight="700" '
           f'letter-spacing="1.5">PARTS SCHEDULE</text>')
    x0, usable = bx + 14, bw - 28
    cols = (("#", 0.06), ("PART", 0.40), ("SIZE  L×W×H mm", 0.28), ("MATERIAL", 0.18), ("QTY", 0.08))
    xs, acc = [], x0
    for _, frac in cols:
        xs.append(acc)
        acc += usable * frac
    hy = by + 48
    out += f'<line x1="{x0:.0f}" y1="{hy:.0f}" x2="{x0 + usable:.0f}" y2="{hy:.0f}" stroke="{_INK}" stroke-width="0.9"/>'
    for (label, _), x in zip(cols, xs):
        out += (f'<text x="{x:.0f}" y="{hy - 6:.0f}" fill="{_MUTE}" font-size="10" '
                f'font-weight="700" letter-spacing="0.5">{label}</text>')
    ry, row_h = hy + 24, 22.0
    max_rows = max(0, int((bh - (ry - by) - 12) / row_h))
    for r in rows[:max_rows]:
        vals = (r["tag"], r["part"], r["size"], r["material"], f'{r["qty"]}×')
        for (_, _), x, val in zip(cols, xs, vals):
            out += f'<text x="{x:.0f}" y="{ry:.0f}" fill="{_INK}" font-size="11">{_esc(str(val))[:34]}</text>'
        out += (f'<line x1="{x0:.0f}" y1="{ry + 7:.0f}" x2="{x0 + usable:.0f}" y2="{ry + 7:.0f}" '
                f'stroke="{_HAIR}" stroke-width="0.5"/>')
        ry += row_h
    if len(rows) > max_rows:
        out += f'<text x="{x0:.0f}" y="{ry:.0f}" fill="{_MUTE}" font-size="10">+ {len(rows) - max_rows} more part(s)…</text>'
    return out


def _overall_panel(bx: float, by: float, bw: float, bh: float,
                   dims_m: tuple[float, float, float], rows: list[dict]) -> str:
    """Overall bounding dimensions + a de-duplicated materials list."""
    length, depth, height = dims_m
    out = (f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" stroke="{_HAIR}" stroke-width="1"/>'
           f'<text x="{bx + 12}" y="{by + 22}" fill="{_INK}" font-size="14" font-weight="700" '
           f'letter-spacing="1.5">OVERALL</text>')
    yy = by + 54
    for label, m in (("Length", length), ("Depth", depth), ("Height", height)):
        out += (f'<text x="{bx + 12}" y="{yy:.0f}" fill="{_MUTE}" font-size="11">{label}</text>'
                f'<text x="{bx + bw - 12}" y="{yy:.0f}" text-anchor="end" fill="{_INK}" '
                f'font-size="15" font-weight="700">{m * 1000:.0f} mm</text>')
        yy += 26
    yy += 6
    out += f'<line x1="{bx + 12:.0f}" y1="{yy - 14:.0f}" x2="{bx + bw - 12:.0f}" y2="{yy - 14:.0f}" stroke="{_HAIR}" stroke-width="0.6"/>'
    out += (f'<text x="{bx + 12}" y="{yy:.0f}" fill="{_MUTE}" font-size="11">Parts (total)</text>'
            f'<text x="{bx + bw - 12}" y="{yy:.0f}" text-anchor="end" fill="{_INK}" font-size="15" '
            f'font-weight="700">{sum(r["qty"] for r in rows)}</text>')
    yy += 36
    out += f'<text x="{bx + 12}" y="{yy:.0f}" fill="{_INK}" font-size="12" font-weight="700" letter-spacing="1">MATERIALS</text>'
    yy += 24
    mats: list[str] = []
    for r in rows:
        if r["material"] and r["material"] != "—" and r["material"] not in mats:
            mats.append(r["material"])
    for m in mats[:8]:
        out += (f'<circle cx="{bx + 18:.0f}" cy="{yy - 4:.0f}" r="3" fill="{_INK}"/>'
                f'<text x="{bx + 30}" y="{yy:.0f}" fill="{_INK}" font-size="11">{_esc(m)[:26]}</text>')
        yy += 20
    return out


def spec_sheet_svg(graph: dict, meta: dict | None = None) -> str:
    """Product spec sheet — three orthographic views + a parts schedule (BOM) +
    overall dimensions, all from the real kernel solids. The single-object analog
    of ``sheet_svg`` (which draws a building's general arrangement)."""
    meta = meta or {}
    W, H = 1500.0, 1060.0
    tb = 100.0
    body = f'<rect x="16" y="16" width="{W - 32:.0f}" height="{H - 32:.0f}" fill="none" stroke="{_INK}" stroke-width="1.5"/>'

    # three orthographic views across the top
    vw, vh = (W - 48) / 3.0, 470.0
    fc, fo, fs = _elevation_data(graph)     # front
    dc, do, ds = _side_data(graph)          # side
    tc, to, ts = _top_data(graph)           # top
    front, mpp = _panel(fc, fo, 24, 24, vw, vh, "FRONT", fs)
    side, _ = _panel(dc, do, 24 + vw, 24, vw, vh, "SIDE", ds)
    top, _ = _panel(tc, to, 24 + 2 * vw, 24, vw, vh, "TOP", ts)
    body += front + side + top
    body += _scale_bar(40, 24 + vh - 22, mpp)

    # schedule (left) + overall/materials (right), below the views
    sy = 24 + vh + 16
    sh = H - sy - 24 - tb - 16
    dims_m = _overall_dims_m(graph)
    rows = _bom_rows(graph)
    body += _schedule_panel(24, sy, W - 48 - 360 - 16, sh, rows)
    body += _overall_panel(W - 24 - 360, sy, 360, sh, dims_m, rows)

    # title block
    ty = H - 24 - tb
    body += f'<rect x="24" y="{ty:.0f}" width="{W - 48:.0f}" height="{tb:.0f}" fill="none" stroke="{_INK}" stroke-width="1.2"/>'
    ptype = _product_type(graph).replace("_", " ")
    name = str(meta.get("project_name") or "KATHA Product")
    lm, dm, hm = dims_m
    body += f'<text x="40" y="{ty + 32:.0f}" fill="{_INK}" font-size="24" font-weight="700" letter-spacing="2">{_esc(name)}</text>'
    body += (f'<text x="40" y="{ty + 58:.0f}" fill="{_PENCIL}" font-size="12" letter-spacing="1.5">'
             f'PRODUCT SPECIFICATION · {_esc(ptype.upper())} · derived from 3D geometry</text>')
    body += (f'<text x="40" y="{ty + 82:.0f}" fill="{_MUTE}" font-size="11">'
             f'Overall {lm * 1000:.0f} × {dm * 1000:.0f} × {hm * 1000:.0f} mm (L×D×H) · '
             f'{len(rows)} unique part(s)</text>')
    cells = [("SCALE", str(meta.get("scale") or "NTS")), ("DATE", str(meta.get("date") or "")),
             ("SHEET", str(meta.get("sheet") or "P-101")), ("UNITS", "mm")]
    cw = 150.0
    for i, (k, v) in enumerate(cells):
        cx = W - 24 - cw * (len(cells) - i)
        body += (f'<line x1="{cx:.0f}" y1="{ty:.0f}" x2="{cx:.0f}" y2="{ty + tb:.0f}" stroke="{_INK}" stroke-width="0.8"/>'
                 f'<text x="{cx + 10:.0f}" y="{ty + 24:.0f}" fill="{_MUTE}" font-size="9" letter-spacing="1">{k}</text>'
                 f'<text x="{cx + 10:.0f}" y="{ty + 50:.0f}" fill="{_INK}" font-size="15" font-weight="700">{_esc(v)}</text>')
    return _wrap(body, W, H)


def sheet_svg(graph: dict, meta: dict | None = None) -> str:
    """Compose plan + section + elevation onto one titled A-ratio sheet.

    For a single-object (furniture/product) design, delegates to
    ``spec_sheet_svg`` — a parts schedule + orthographic views instead of a
    building general arrangement."""
    if _is_product(graph):
        return spec_sheet_svg(graph, meta)
    meta = meta or {}
    W, H = 1500.0, 1060.0
    tb = 118.0  # title-block height (room for a code-compliance line)
    body = f'<rect x="16" y="16" width="{W - 32:.0f}" height="{H - 32:.0f}" fill="none" stroke="{_INK}" stroke-width="1.5"/>'

    pw, ph = (W - 48) / 2, (H - 48 - tb) / 2
    pc, po, ps = _plan_data(graph)
    sc_, so, ss = _section_data(graph, None)
    ec, eo, es = _elevation_data(graph)
    plan, mpp = _panel(pc, po, 24, 24, pw, ph, "PLAN", ps)
    sec, _ = _panel(sc_, so, 24 + pw, 24, pw, ph, "SECTION", ss)
    elev, _ = _panel(ec, eo, 24, 24 + ph, W - 48, ph, "ELEVATION", es)
    body += plan + sec + elev
    body += _north(24 + pw - 40, 24 + 60)
    body += _scale_bar(40, 24 + ph - 24, mpp)

    # title block
    ty = H - 24 - tb
    body += f'<rect x="24" y="{ty:.0f}" width="{W - 48:.0f}" height="{tb:.0f}" fill="none" stroke="{_INK}" stroke-width="1.2"/>'
    name = str(meta.get("project_name") or "KATHA Project")
    body += f'<text x="40" y="{ty + 34:.0f}" fill="{_INK}" font-size="24" font-weight="700" letter-spacing="2">{name}</text>'
    region = meta.get("region")
    body += (f'<text x="40" y="{ty + 60:.0f}" fill="{_PENCIL}" font-size="12" letter-spacing="1.5">'
             f'GENERAL ARRANGEMENT · derived from 3D geometry · checked to {code_label(region)}</text>')
    # code-compliance stamp (jurisdiction-specific minimums)
    checks = run_code_checks(graph, region=region)
    _p, _w, nf = tally(checks)
    verdict = "PASS" if nf == 0 else "REVIEW"
    vcol = "#2f7d4f" if nf == 0 else _PENCIL
    body += (f'<text x="40" y="{ty + 94:.0f}" fill="{_MUTE}" font-size="10" letter-spacing="1">CODE</text>'
             f'<rect x="80" y="{ty + 82:.0f}" width="64" height="16" rx="2" fill="{vcol}"/>'
             f'<text x="112" y="{ty + 94:.0f}" text-anchor="middle" fill="#FFFFFF" font-size="10" font-weight="700">{verdict}</text>')
    cx = 162.0
    _COL = {"pass": "#2f7d4f", "warn": "#c98a2e", "fail": "#C8362D", "info": _MUTE}
    for c in checks:
        body += (f'<circle cx="{cx:.0f}" cy="{ty + 89:.0f}" r="4" fill="{_COL.get(c["status"], _MUTE)}"/>'
                 f'<text x="{cx + 9:.0f}" y="{ty + 94:.0f}" fill="{_INK}" font-size="11">{c["label"]}</text>')
        cx += 22 + len(c["label"]) * 6.6
    cells = [("SCALE", str(meta.get("scale") or "NTS")), ("DATE", str(meta.get("date") or "")),
             ("SHEET", str(meta.get("sheet") or "A-101")), ("REV", str(meta.get("rev") or "—"))]
    cw = 150.0
    for i, (k, v) in enumerate(cells):
        cx = W - 24 - cw * (len(cells) - i)
        body += (f'<line x1="{cx:.0f}" y1="{ty:.0f}" x2="{cx:.0f}" y2="{ty + tb:.0f}" stroke="{_INK}" stroke-width="0.8"/>'
                 f'<text x="{cx + 10:.0f}" y="{ty + 24:.0f}" fill="{_MUTE}" font-size="9" letter-spacing="1">{k}</text>'
                 f'<text x="{cx + 10:.0f}" y="{ty + 50:.0f}" fill="{_INK}" font-size="15" font-weight="700">{v}</text>')
    return _wrap(body, W, H)


# ── CAD / print export ────────────────────────────────────────────────────────
def sheet_dxf(graph: dict) -> bytes:
    """Plan + section + elevation as DXF (R2010) polylines on layers, laid out
    side by side so they don't overlap. Opens in AutoCAD / Revit / ArchiCAD. A
    single-object design emits its FRONT / SIDE / TOP orthographic views."""
    import io

    import ezdxf

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    if _is_product(graph):
        layer_colors = (("FRONT", 7), ("SIDE", 1), ("TOP", 3))
        views = [("FRONT", _elevation_data(graph)), ("SIDE", _side_data(graph)),
                 ("TOP", _top_data(graph))]
    else:
        layer_colors = (("PLAN", 7), ("SECTION", 1), ("ELEVATION", 3))
        views = [("PLAN", _plan_data(graph)), ("SECTION", _section_data(graph, None)),
                 ("ELEVATION", _elevation_data(graph))]
    for name, color in layer_colors:
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    gap, cursor = 3.0, 0.0
    for layer, (cut, outline, _sub) in views:
        polys = outline + cut
        if not polys:
            continue
        minx, miny, maxx, maxy = _bounds(polys)
        dx = cursor - minx
        for poly in polys:
            if len(poly) >= 2:
                msp.add_lwpolyline([(p[0] + dx, p[1] - miny) for p in poly],
                                   close=True, dxfattribs={"layer": layer})
        cursor += (maxx - minx) + gap
    s = io.StringIO()
    doc.write(s)
    return s.getvalue().encode("utf-8")


def sheet_pdf(graph: dict, meta: dict | None = None) -> bytes:
    """Plan + section + elevation + title block as a landscape A3 PDF (reportlab
    canvas, drawn from the polygons — no SVG conversion). A single-object design
    delegates to ``spec_sheet_pdf``."""
    if _is_product(graph):
        return spec_sheet_pdf(graph, meta)
    import io

    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.pdfgen import canvas

    meta = meta or {}
    buf = io.BytesIO()
    W, H = landscape(A3)
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setLineWidth(1.2)
    c.rect(20, 20, W - 40, H - 40)
    tb = 64.0
    pw, ph = (W - 56) / 2, (H - 56 - tb) / 2

    def panel(cut, outline, bx, by, bw, bh, title):
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0.9, 0.89, 0.86)
        c.rect(bx, by, bw, bh, stroke=1, fill=0)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Courier-Bold", 9)
        c.drawString(bx + 8, by + bh - 14, title)
        allp = cut + outline
        if not allp:
            return
        minx, miny, maxx, maxy = _bounds(allp)
        w, h = (maxx - minx) or 1, (maxy - miny) or 1
        m = 16.0
        sc = min((bw - 2 * m) / w, (bh - 2 * m - 14) / h)
        ox = bx + m + ((bw - 2 * m) - w * sc) / 2
        oy = by + m + ((bh - 2 * m - 14) - h * sc) / 2

        def draw(polys, fill):
            p = c.beginPath()
            for poly in polys:
                if len(poly) < 3:
                    continue
                p.moveTo(ox + (poly[0][0] - minx) * sc, oy + (poly[0][1] - miny) * sc)
                for q in poly[1:]:
                    p.lineTo(ox + (q[0] - minx) * sc, oy + (q[1] - miny) * sc)
                p.close()
            c.drawPath(p, stroke=1, fill=1 if fill else 0)

        c.setStrokeColorRGB(0.72, 0.71, 0.69)
        c.setLineWidth(0.4)
        draw(outline, False)
        c.setStrokeColorRGB(0.1, 0.1, 0.1)
        c.setLineWidth(1.1)
        c.setFillColorRGB(0.85, 0.84, 0.82)
        draw(cut, True)
        c.setFillColorRGB(0, 0, 0)

    panel(*_plan_data(graph)[:2], 28, 28 + tb + ph, pw, ph, "PLAN")
    panel(*_section_data(graph, None)[:2], 28 + pw, 28 + tb + ph, pw, ph, "SECTION")
    panel(*_elevation_data(graph)[:2], 28, 28 + tb, W - 56, ph, "ELEVATION")

    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(1)
    c.rect(28, 28, W - 56, tb)
    c.setFont("Courier-Bold", 16)
    c.drawString(40, 28 + tb - 26, str(meta.get("project_name") or "KATHA Project"))
    c.setFillColorRGB(0.78, 0.21, 0.18)
    c.setFont("Courier", 9)
    c.drawString(40, 28 + tb - 44, "GENERAL ARRANGEMENT - derived from 3D geometry")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawRightString(W - 40, 28 + 20, f"SCALE {meta.get('scale') or 'NTS'}    SHEET {meta.get('sheet') or 'A-101'}")
    c.showPage()
    c.save()
    return buf.getvalue()


def spec_sheet_pdf(graph: dict, meta: dict | None = None) -> bytes:
    """Product spec sheet as a landscape A3 PDF — three orthographic views, a
    parts schedule, and overall dimensions (the single-object analog of
    ``sheet_pdf``)."""
    import io

    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.pdfgen import canvas

    meta = meta or {}
    buf = io.BytesIO()
    W, H = landscape(A3)
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setLineWidth(1.2)
    c.rect(20, 20, W - 40, H - 40)

    def panel(cut, outline, bx, by, bw, bh, title):
        c.setLineWidth(0.5)
        c.setStrokeColorRGB(0.9, 0.89, 0.86)
        c.rect(bx, by, bw, bh, stroke=1, fill=0)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont("Courier-Bold", 9)
        c.drawString(bx + 8, by + bh - 14, title)
        allp = cut + outline
        if not allp:
            return
        minx, miny, maxx, maxy = _bounds(allp)
        w, h = (maxx - minx) or 1, (maxy - miny) or 1
        m = 16.0
        sc = min((bw - 2 * m) / w, (bh - 2 * m - 14) / h)
        ox = bx + m + ((bw - 2 * m) - w * sc) / 2
        oy = by + m + ((bh - 2 * m - 14) - h * sc) / 2
        p = c.beginPath()
        for poly in outline:
            if len(poly) < 3:
                continue
            p.moveTo(ox + (poly[0][0] - minx) * sc, oy + (poly[0][1] - miny) * sc)
            for q in poly[1:]:
                p.lineTo(ox + (q[0] - minx) * sc, oy + (q[1] - miny) * sc)
            p.close()
        c.setStrokeColorRGB(0.1, 0.1, 0.1)
        c.setLineWidth(1.0)
        c.drawPath(p, stroke=1, fill=0)
        c.setFillColorRGB(0, 0, 0)

    tb = 92.0
    top_h = (H - 56 - tb) * 0.52
    vw = (W - 56) / 3.0
    vy = H - 28 - top_h
    panel(*_elevation_data(graph)[:2], 28, vy, vw, top_h, "FRONT")
    panel(*_side_data(graph)[:2], 28 + vw, vy, vw, top_h, "SIDE")
    panel(*_top_data(graph)[:2], 28 + 2 * vw, vy, vw, top_h, "TOP")

    rows = _bom_rows(graph)
    lm, dm, hm = _overall_dims_m(graph)
    sy = 28 + tb
    sh = vy - sy - 10

    # parts schedule (left)
    sx, sw = 28, W - 56 - 300 - 12
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(0.9, 0.89, 0.86)
    c.rect(sx, sy, sw, sh)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Courier-Bold", 11)
    c.drawString(sx + 10, sy + sh - 18, "PARTS SCHEDULE")
    heads = [("#", sx + 12), ("PART", sx + 60), ("SIZE L/W/H mm", sx + sw * 0.42),
             ("MATERIAL", sx + sw * 0.68), ("QTY", sx + sw - 44)]
    ry = sy + sh - 40
    c.setFont("Courier-Bold", 8)
    for label, hx in heads:
        c.drawString(hx, ry, label)
    ry -= 6
    c.line(sx + 10, ry, sx + sw - 10, ry)
    ry -= 14
    c.setFont("Courier", 8)
    row_h = 15.0
    max_rows = max(0, int((ry - sy - 8) / row_h))
    hxs = [hx for _, hx in heads]
    for r in rows[:max_rows]:
        for val, hx in zip((r["tag"], r["part"], r["size"], r["material"], f'{r["qty"]}x'), hxs):
            c.drawString(hx, ry, str(val)[:26])
        ry -= row_h
    if len(rows) > max_rows:
        c.drawString(sx + 12, ry, f"+ {len(rows) - max_rows} more part(s)...")

    # overall (right)
    ox_, ow = W - 28 - 300, 300
    c.setStrokeColorRGB(0.9, 0.89, 0.86)
    c.rect(ox_, sy, ow, sh)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Courier-Bold", 11)
    c.drawString(ox_ + 10, sy + sh - 18, "OVERALL")
    c.setFont("Courier", 10)
    yy = sy + sh - 42
    for label, mval in (("Length", lm), ("Depth", dm), ("Height", hm)):
        c.drawString(ox_ + 12, yy, label)
        c.drawRightString(ox_ + ow - 12, yy, f"{mval * 1000:.0f} mm")
        yy -= 20
    yy -= 6
    c.drawString(ox_ + 12, yy, "Parts (total)")
    c.drawRightString(ox_ + ow - 12, yy, str(sum(r["qty"] for r in rows)))

    # title block
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(1)
    c.rect(28, 28, W - 56, tb)
    c.setFont("Courier-Bold", 16)
    c.drawString(40, 28 + tb - 26, str(meta.get("project_name") or "KATHA Product"))
    c.setFillColorRGB(0.78, 0.21, 0.18)
    c.setFont("Courier", 9)
    ptype = _product_type(graph).replace("_", " ").upper()
    c.drawString(40, 28 + tb - 44, f"PRODUCT SPECIFICATION - {ptype} - derived from 3D geometry")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawRightString(W - 40, 28 + 20,
                      f"SCALE {meta.get('scale') or 'NTS'}    SHEET {meta.get('sheet') or 'P-101'}    UNITS mm")
    c.showPage()
    c.save()
    return buf.getvalue()
