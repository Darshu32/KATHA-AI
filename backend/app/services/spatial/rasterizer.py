"""Render engine — solids → base + depth + normal + exact hotspots.

A dependency-free numpy rasterizer. Its job is not beauty (that's the finish
pass); its job is a *geometrically correct* view of the real kernel geometry
from a *real camera* — giving us the two things a 2D image model cannot:
consistent camera control and exact object hotspots (projected through the same
matrix, no vision guessing). Triangles are clipped against the near plane so
interior/close cameras stay artefact-free.
"""

from __future__ import annotations

import numpy as np


def _normalize(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def look_at(eye, target, up=(0, 1, 0)):
    eye, target, up = (np.asarray(a, float) for a in (eye, target, up))
    f = _normalize(target - eye)
    s = _normalize(np.cross(f, up))
    u = np.cross(s, f)
    M = np.eye(4)
    M[0, :3], M[1, :3], M[2, :3] = s, u, -f
    M[0, 3], M[1, 3], M[2, 3] = -s @ eye, -u @ eye, f @ eye
    return M


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fovy_deg) / 2)
    M = np.zeros((4, 4))
    M[0, 0] = f / aspect
    M[1, 1] = f
    M[2, 2] = (far + near) / (near - far)
    M[2, 3] = (2 * far * near) / (near - far)
    M[3, 2] = -1.0
    return M


def orbit_camera(bbox, azimuth_deg=35.0, elev_deg=22.0, dist_factor=2.3, fov=42.0):
    """Aerial framing camera around a scene AABB (exterior/site scale)."""
    lo, hi = np.array(bbox[:3], float), np.array(bbox[3:], float)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2) or 1.0
    az, el = np.radians(azimuth_deg), np.radians(elev_deg)
    d = np.array([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)])
    eye = center + d * radius * dist_factor
    return dict(eye=eye, target=center, fov=fov,
               near=max(radius * 0.02, 0.05), far=radius * 12)


def interior_camera(room_l, room_w, room_h, azimuth_deg=45.0, elev_deg=24.0):
    """Dollhouse camera outside one corner, looking across the room. Returns the
    camera and the set of wall sides to cull (the near walls facing the eye)."""
    center = np.array([room_l / 2, room_h * 0.52, room_w / 2])
    diag = float(np.hypot(room_l, room_w)) or 3.0
    az, el = np.radians(azimuth_deg), np.radians(elev_deg)
    d = np.array([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)])
    eye = center + d * diag * 1.05
    cam = dict(eye=eye, target=center, fov=52.0, near=0.05, far=diag * 8)
    cull = set()
    for side, n in (("-x", (-1, 0, 0)), ("+x", (1, 0, 0)), ("-z", (0, 0, -1)), ("+z", (0, 0, 1))):
        if np.dot(np.array(n, float), eye - center) > 0:   # outward face toward camera
            cull.add(side)
    return cam, cull


_STRUCTURAL = {"ground", "wall", "floor", "slab", "ceiling"}


def _clip_near(pts, near):
    """Sutherland–Hodgman clip of a view-space polygon against z <= -near."""
    out = []
    n = len(pts)
    for i in range(n):
        cur, nxt = pts[i], pts[(i + 1) % n]
        cur_in, nxt_in = cur[2] <= -near, nxt[2] <= -near
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:
            t = (-near - cur[2]) / (nxt[2] - cur[2])
            out.append(cur + t * (nxt - cur))
    return out


def render(solids, cam, W=1200, H=800, bg=(0.9, 0.91, 0.93), ss=2):
    """Rasterise solids from `cam`. Returns (rgb, depth, normal, id_buf, hotspots).

    Renders ``ss``× oversampled and box-downsamples the result, so edges come out
    smooth instead of stair-stepped — the single biggest quality win for the clay
    render. Shading is a deterministic two-light studio rig (key + fill) over a
    hemisphere ambient, for a softer, more "rendered" look than one bare lamp —
    still fully deterministic, no img2img, no external service.
    """
    ss = max(1, int(ss))
    Wr, Hr = W * ss, H * ss              # oversampled render size; W×H is the output
    V = look_at(cam["eye"], cam["target"])
    P = perspective(cam["fov"], Wr / Hr, cam["near"], cam["far"])
    near = cam["near"]
    Rn = V[:3, :3]
    key_dir = _normalize(np.array([0.35, 0.9, 0.45]))     # key light — high, to one side
    fill_dir = _normalize(np.array([-0.55, 0.4, -0.35]))  # soft fill — opposite, lifts shadow

    rgb = np.tile(np.array(bg, np.float32), (Hr, Wr, 1))
    zbuf = np.full((Hr, Wr), np.inf)
    nrm = np.full((Hr, Wr, 3), 0.5, np.float32)
    depthv = np.full((Hr, Wr), np.nan)
    idbuf = np.full((Hr, Wr), -1, np.int32)

    for oi, s in enumerate(solids):
        if s.verts is None or not len(s.verts):
            continue
        vh = np.hstack([s.verts, np.ones((len(s.verts), 1))])
        vview = (vh @ V.T)[:, :3]        # view-space vertices
        for tri in s.tris:
            i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
            p0, p1, p2 = vview[i0], vview[i1], vview[i2]
            in0, in1, in2 = p0[2] <= -near, p1[2] <= -near, p2[2] <= -near
            if not (in0 or in1 or in2):
                continue                  # fully behind near plane
            if in0 and in1 and in2:
                fans = [(p0, p1, p2)]
            else:
                poly = _clip_near([p0, p1, p2], near)
                if len(poly) < 3:
                    continue
                fans = [(poly[0], poly[k], poly[k + 1]) for k in range(1, len(poly) - 1)]

            fn = _normalize(np.cross(s.verts[i1] - s.verts[i0], s.verts[i2] - s.verts[i0]))
            key = max(0.0, float(fn @ key_dir))
            fill = max(0.0, float(fn @ fill_dir))
            hemi = 0.5 + 0.5 * float(fn[1])   # up-facing catches "sky", down-facing "ground"
            shade = 0.30 + 0.20 * hemi + 0.60 * key + 0.16 * fill
            col = np.clip(np.array(s.color, np.float32) * shade, 0, 1)
            nv = (_normalize(Rn @ fn) * 0.5 + 0.5).astype(np.float32)

            for a3, b3, c3 in fans:
                _raster_tri(P, a3, b3, c3, Wr, Hr, col, nv, oi, rgb, zbuf, nrm, depthv, idbuf)

    hotspots = _project_hotspots(solids, P @ V, Wr, Hr)   # normalised → resolution-independent
    depth_gray = _depth_to_gray(depthv)
    if ss > 1:                            # box-downsample every buffer to the output size
        rgb = rgb.reshape(H, ss, W, ss, 3).mean(axis=(1, 3))
        nrm = nrm.reshape(H, ss, W, ss, 3).mean(axis=(1, 3))
        depth_gray = depth_gray.reshape(H, ss, W, ss).mean(axis=(1, 3))
        idbuf = np.ascontiguousarray(idbuf.reshape(H, ss, W, ss)[:, 0, :, 0])
    return rgb, depth_gray, nrm, idbuf, hotspots


def _proj(P, vpt, W, H):
    c = P @ np.array([vpt[0], vpt[1], vpt[2], 1.0])
    w = c[3]
    if w <= 1e-6:
        return None
    ndc = c[:3] / w
    return ((ndc[0] * 0.5 + 0.5) * W, (0.5 - ndc[1] * 0.5) * H, ndc[2], vpt[2], w)


def _raster_tri(P, a3, b3, c3, W, H, col, nv, oi, rgb, zbuf, nrm, depthv, idbuf):
    A, B, C = _proj(P, a3, W, H), _proj(P, b3, W, H), _proj(P, c3, W, H)
    if A is None or B is None or C is None:
        return
    (x0, y0, d0, vz0, w0), (x1, y1, d1, vz1, w1), (x2, y2, d2, vz2, w2) = A, B, C
    minx, maxx = int(max(0, np.floor(min(x0, x1, x2)))), int(min(W - 1, np.ceil(max(x0, x1, x2))))
    miny, maxy = int(max(0, np.floor(min(y0, y1, y2)))), int(min(H - 1, np.ceil(max(y0, y1, y2))))
    if minx > maxx or miny > maxy:
        return
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-9:
        return
    gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
    a = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denom
    b = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denom
    c = 1 - a - b
    inside = (a >= 0) & (b >= 0) & (c >= 0)
    if not inside.any():
        return
    depth = a * d0 + b * d1 + c * d2
    sub = zbuf[miny:maxy + 1, minx:maxx + 1]
    win = inside & (depth < sub)
    if not win.any():
        return
    invw = a / w0 + b / w1 + c / w2
    vz_pc = (a * vz0 / w0 + b * vz1 / w1 + c * vz2 / w2) / np.where(invw == 0, 1, invw)
    ys, xs = np.nonzero(win)
    YY, XX = ys + miny, xs + minx
    zbuf[YY, XX] = depth[win]
    rgb[YY, XX] = col
    nrm[YY, XX] = nv
    depthv[YY, XX] = vz_pc[win]
    idbuf[YY, XX] = oi


def _project_hotspots(solids, MVP, W, H):
    out = []
    for s in solids:
        if s.type in _STRUCTURAL or s.verts is None or not len(s.verts):
            continue
        lo, hi = s.verts.min(0), s.verts.max(0)
        corners = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]], [lo[0], hi[1], lo[2]],
                            [hi[0], hi[1], lo[2]], [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                            [lo[0], hi[1], hi[2]], [hi[0], hi[1], hi[2]]])
        ch = np.hstack([corners, np.ones((8, 1))]) @ MVP.T
        w = ch[:, 3]
        if (w <= 1e-6).any():
            continue
        ndc = ch[:, :3] / w[:, None]
        xs = (ndc[:, 0] * 0.5 + 0.5) * W
        ys = (0.5 - ndc[:, 1] * 0.5) * H
        x0, x1 = max(0, float(xs.min())), min(W, float(xs.max()))
        y0, y1 = max(0, float(ys.min())), min(H, float(ys.max()))
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        out.append({"id": s.id, "name": s.name, "type": s.type,
                    "x": round(x0 / W, 4), "y": round(y0 / H, 4),
                    "w": round((x1 - x0) / W, 4), "h": round((y1 - y0) / H, 4),
                    "grounded": True})
    return out


def _depth_to_gray(depthv, bg=0.98):
    out = np.full(depthv.shape, bg, np.float32)
    mask = ~np.isnan(depthv)
    if mask.any():
        d = -depthv[mask]
        d0, d1 = d.min(), d.max()
        norm = (d - d0) / (d1 - d0) if d1 > d0 else np.zeros_like(d)
        out[mask] = (1.0 - norm).astype(np.float32)
    return out
