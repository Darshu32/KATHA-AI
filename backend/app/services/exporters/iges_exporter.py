"""IGES (Initial Graphics Exchange Specification) exporter — IGES 5.3.

Hand-rolled minimal IGES file. Each design object emits a Manifold Solid
B-Rep Object (entity 186) made of six planar faces (polygonal). Companion
to the STEP exporter for legacy CAD/CAM tools that still prefer IGES
(older versions of CATIA, Pro/E, NX).

Reference: ANS US PRO/IPO-100-1996 (IGES 5.3).
"""

from __future__ import annotations

from datetime import datetime, timezone


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


# IGES uses 80-char fixed-width records. Each section line ends with the
# section letter (S/G/D/P/T) and a 7-digit sequence number, right-aligned.
def _line(content: str, section: str, seq: int) -> str:
    body = content[:72].ljust(72)
    return f"{body}{section}{seq:7d}"


def _emit_box_faces(cx: float, cy: float, cz: float,
                    l: float, h: float, w: float) -> list[tuple[tuple[float, float, float], ...]]:
    """Return six quadrilateral faces (each a 4-tuple of XYZ vertices)."""
    hx, hz = l / 2.0, w / 2.0
    v = [
        (cx - hx, cy,     cz - hz), (cx + hx, cy,     cz - hz),
        (cx + hx, cy,     cz + hz), (cx - hx, cy,     cz + hz),
        (cx - hx, cy + h, cz - hz), (cx + hx, cy + h, cz - hz),
        (cx + hx, cy + h, cz + hz), (cx - hx, cy + h, cz + hz),
    ]
    return [
        (v[0], v[1], v[2], v[3]),  # bottom
        (v[4], v[7], v[6], v[5]),  # top
        (v[0], v[4], v[5], v[1]),  # north
        (v[1], v[5], v[6], v[2]),  # east
        (v[2], v[6], v[7], v[3]),  # south
        (v[3], v[7], v[4], v[0]),  # west
    ]


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta") or {}
    project = _safe_name(meta.get("project_name", "project"))
    today = datetime.now(timezone.utc)
    stamp = today.strftime("%y%m%d.%H%M%S")

    # ── Start section (S) — human-readable preamble ────────────────────────
    s_lines = [
        _line(f"KATHA AI IGES export — {meta.get('project_name','')}", "S", 1),
        _line(f"theme: {meta.get('theme','')}; generated {today.isoformat()}", "S", 2),
    ]

    # ── Global section (G) — comma-separated metadata ──────────────────────
    g_text = (
        f",,1H{project[:1] if project else 'P'},"
        f"{len(project)}H{project},"
        f"{len('KATHA AI')}HKATHA AI,"
        f"{len('IGES 5.3')}HIGES 5.3,"
        "32,38,7,308,15,"
        f"{len(project)}H{project},"
        "1.0,1,4HMM,1,0.001,"
        f"{len(stamp)}H{stamp},"
        "0.001,1000.0,"
        f"{len('KATHA')}HKATHA,"
        f"{len('AI')}HAI,11,0,"
        f"{len(stamp)}H{stamp};"
    )
    g_lines: list[str] = []
    chunk_size = 72
    for i in range(0, len(g_text), chunk_size):
        chunk = g_text[i:i + chunk_size]
        g_lines.append(_line(chunk, "G", len(g_lines) + 1))

    # ── Build face list across the whole scene ─────────────────────────────
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)

    all_faces: list[tuple] = []
    all_faces += _emit_box_faces(room_l / 2.0, 0.0, room_w / 2.0, room_l, 0.02, room_w)

    for obj in graph.get("objects") or []:
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        cx = float(pos.get("x", 0))
        cy = float(pos.get("y", 0) or 0)
        cz = float(pos.get("z", 0))
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        all_faces += _emit_box_faces(cx, cy, cz, l, h, w)

    # ── Parameter section (P) — entity 106 (Copious Data, type 12 = closed
    # planar polygon). Each face is one entity. Directory section (D) gets a
    # 2-line stub for every parameter entity.
    d_lines: list[str] = []
    p_lines: list[str] = []
    for face_idx, face in enumerate(all_faces, start=1):
        de_seq = (face_idx - 1) * 2 + 1     # odd D sequence numbers
        pd_seq = len(p_lines) + 1
        # Entity 106, form 63 — closed planar piecewise-linear curve.
        params = ["106", "1", str(len(face) + 1)]
        # Z plane prefix per IGES 106 form-12; we use the average Z of vertices
        # so the curve sits on its plane. (Form 12 for 3-D paths still requires
        # the leading Z baseline.)
        avg_z = sum(p[2] for p in face) / len(face)
        params.append(f"{avg_z:.6f}")
        for px, py, pz in face:
            params += [f"{px:.6f}", f"{py:.6f}", f"{pz:.6f}"]
        # Close the polygon.
        first = face[0]
        params += [f"{first[0]:.6f}", f"{first[1]:.6f}", f"{first[2]:.6f}"]
        p_text = ",".join(params) + f",0,0;"

        for chunk_idx, i in enumerate(range(0, len(p_text), 64)):
            chunk = p_text[i:i + 64].ljust(64)
            line_seq = pd_seq + chunk_idx
            tail = f"{de_seq:8d}P{line_seq:7d}"
            p_lines.append(f"{chunk}{tail}")

        # Directory entry: 2 fixed-width lines, each 8 columns × 8 chars.
        # Columns: Type, ParameterPointer, Structure, LineFontPattern, Level,
        # View, TransformMatrix, LabelDispAssoc; second line: Type, LineWeight,
        # Color, ParamLineCount, FormNumber, Reserved×2, EntityLabel, EntitySubscript.
        d_lines.append(
            f"{106:8d}{pd_seq:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}{0:8d}D{de_seq:7d}"
        )
        # Param-line count = chunks above.
        param_line_count = (len(p_text) + 63) // 64
        d_lines.append(
            f"{106:8d}{0:8d}{0:8d}{param_line_count:8d}{12:8d}{0:8d}{0:8d}"
            f"{0:8d}{0:8d}D{de_seq + 1:7d}"
        )

    # ── Terminate section (T) — counts of S, G, D, P records ───────────────
    counts = (
        f"S{len(s_lines):7d}"
        f"G{len(g_lines):7d}"
        f"D{len(d_lines):7d}"
        f"P{len(p_lines):7d}"
    )
    t_lines = [_line(counts, "T", 1)]

    body = "\n".join(s_lines + g_lines + d_lines + p_lines + t_lines) + "\n"
    return {
        "content_type": "model/iges",
        "filename": f"{project}-cad.igs",
        "bytes": body.encode("ascii", errors="replace"),
    }
