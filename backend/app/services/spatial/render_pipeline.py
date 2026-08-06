"""Render pipeline — spec → photoreal image + exact hotspots, in one call.

This is the entry point the generator uses. It picks the camera (aerial for
site/exterior, dollhouse for interiors), culls the walls between camera and
room, rasterises real geometry, then runs the finish pass. Returns everything
the generator needs; returns ``None`` when the scene is too degenerate to render
(no objects, kernel failure) so the caller can fall back to the legacy path.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

from app.services.spatial.finish import build_finish_prompt, finish_render
from app.services.spatial.kernel import Solid, _room_dims, build_scene
from app.services.spatial.rasterizer import interior_camera, orbit_camera, render

logger = logging.getLogger(__name__)

_STRUCTURAL = {"ground", "wall", "floor", "slab", "ceiling"}


@dataclass
class RenderResult:
    image_bytes: bytes          # the display image (finished if available, else base clay)
    hotspots: list[dict]        # exact camera-projected object boxes
    base_bytes: bytes           # clay geometry render
    depth_bytes: bytes          # depth map (finish-pass / ControlNet conditioning)
    normal_bytes: bytes         # normal map
    provider: str               # e.g. "katha-kernel+openai-gpt-image-1"
    kind: str                   # "interior" | "exterior"
    finished: bool              # whether a photoreal finish was applied
    mime: str = "image/png"


def _to_png(arr) -> bytes:
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build_and_raster(graph: dict, width: int, height: int):
    """CPU-bound: kernel + camera + rasterise. Runs in a worker thread."""
    solids, bbox, kind = build_scene(graph)
    floor_count = sum(1 for s in solids if s.type == "floor")
    # Meaningful to show if there's furniture OR it's a multi-room plan (the
    # rooms themselves are the subject, even before they're furnished).
    if not any(s.type not in _STRUCTURAL for s in solids) and floor_count < 2:
        return None

    if kind == "interior" and floor_count >= 2:
        # Multi-room: frame the WHOLE plan as an elevated dollhouse looking down
        # into the open-top rooms. The single-room ``interior_camera`` frames
        # only ``spaces[0]``, which crops a multi-room apartment badly.
        cam = orbit_camera(bbox, azimuth_deg=32.0, elev_deg=54.0, dist_factor=2.0, fov=40.0)
        render_solids = solids
    elif kind == "interior":
        rl, rw, rh = _room_dims(graph)
        cam, cull = interior_camera(rl, rw, rh)
        render_solids = [s for s in solids if s.side not in cull]
    else:
        non_ground = [s for s in solids if s.type != "ground" and s.verts is not None and len(s.verts)]
        lo = np.min([s.verts.min(0) for s in non_ground], 0)
        hi = np.max([s.verts.max(0) for s in non_ground], 0)
        cam = orbit_camera((lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))
        render_solids = solids

    rgb, depth, nrm, idbuf, hotspots = render(render_solids, cam, W=width, H=height)
    coverage = float(np.count_nonzero(idbuf >= 0)) / idbuf.size
    if coverage < 0.02:  # camera saw essentially nothing — let the caller fall back
        logger.warning("spatial render coverage too low (%.3f) kind=%s", coverage, kind)
        return None
    return _to_png(rgb), _to_png(depth), _to_png(nrm), hotspots, kind


async def render_design(graph: dict, *, width: int = 1200, height: int = 800,
                        finish: bool = True) -> RenderResult | None:
    """Spec → RenderResult, or None to signal the caller to use the legacy path."""
    try:
        built = await asyncio.to_thread(_build_and_raster, graph, width, height)
    except Exception as exc:  # noqa: BLE001 — geometry must never break generation
        logger.warning("spatial kernel/raster failed: %s", exc)
        return None
    if not built:
        return None
    base_png, depth_png, normal_png, hotspots, kind = built

    image_bytes, provider, finished = base_png, "katha-kernel", False
    if finish:
        try:
            res = await finish_render(
                base_png, depth_png,
                build_finish_prompt(graph, kind=kind),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("finish pass failed: %s", exc)
            res = None
        if res:
            image_bytes = res["bytes"]
            provider = f"katha-kernel+{res['provider']}"
            finished = True

    return RenderResult(
        image_bytes=image_bytes, hotspots=hotspots, base_bytes=base_png,
        depth_bytes=depth_png, normal_bytes=normal_png, provider=provider,
        kind=kind, finished=finished,
    )


# ── Imported-mesh path (Layer 5B, Tier 1: upload → geometry) ──────────────────
def _raster_mesh(verts, tris, width: int, height: int):
    """CPU-bound: wrap an imported mesh as a Solid, frame it, rasterise.

    No kernel — the software rasteriser draws the triangles directly, so an
    arbitrary (non-watertight) uploaded mesh renders without a Manifold."""
    v = np.asarray(verts, np.float32)
    t = np.asarray(tris, np.int32)
    if not len(v) or not len(t):
        return None
    lo, hi = v.min(0), v.max(0)
    bbox = (float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2]))
    longest = float((hi - lo).max()) or 1.0
    kind = "product" if longest < 3.0 else "exterior"   # object vs building scale
    solid = Solid(id="model", name="Imported model", type="model",
                  color=(0.62, 0.60, 0.58), manifold=None, side=None, verts=v, tris=t)
    cam = orbit_camera(bbox, elev_deg=26.0 if kind == "product" else 18.0)
    rgb, depth, nrm, idbuf, hotspots = render([solid], cam, W=width, H=height)
    coverage = float(np.count_nonzero(idbuf >= 0)) / idbuf.size
    if coverage < 0.01:
        logger.warning("mesh render coverage too low (%.3f)", coverage)
        return None
    return _to_png(rgb), _to_png(depth), _to_png(nrm), hotspots, kind


async def render_mesh(verts, tris, *, width: int = 1200, height: int = 800,
                      finish: bool = True, style: str | None = None) -> RenderResult | None:
    """Imported mesh (verts (N,3), tris (M,3)) → RenderResult. Layer 5B Tier 1:
    straight to the rasteriser + finish pass, no spec/kernel. ``style`` is an
    optional material/finish hint (e.g. "walnut and tan leather") — an uploaded
    mesh carries no materials, so without it the finish picks a neutral one.
    Returns None when the mesh is degenerate (caller surfaces a friendly error)."""
    try:
        built = await asyncio.to_thread(_raster_mesh, verts, tris, width, height)
    except Exception as exc:  # noqa: BLE001 — geometry must never break the request
        logger.warning("mesh raster failed: %s", exc)
        return None
    if not built:
        return None
    base_png, depth_png, normal_png, hotspots, kind = built

    image_bytes, provider, finished = base_png, "katha-mesh", False
    if finish:
        graph = {"design_type": kind, "style": {"primary": style} if style else {}}
        try:
            res = await finish_render(base_png, depth_png,
                                      build_finish_prompt(graph, kind=kind))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mesh finish failed: %s", exc)
            res = None
        if res:
            image_bytes = res["bytes"]
            provider = f"katha-mesh+{res['provider']}"
            finished = True

    return RenderResult(
        image_bytes=image_bytes, hotspots=hotspots, base_bytes=base_png,
        depth_bytes=depth_png, normal_bytes=normal_png, provider=provider,
        kind=kind, finished=finished,
    )


# ── Decomposed-mesh path (Tier 2: per-part solids → per-part hotspots) ─────────
def _raster_parts(parts, width: int, height: int):
    """One Solid per part (real triangles) rendered together, so each part gets
    its own id in the hotspot buffer → individually selectable."""
    solids, los, his = [], [], []
    for p in parts:
        v = np.asarray(p["verts"], np.float32)
        t = np.asarray(p["tris"], np.int32)
        if not len(v) or not len(t):
            continue
        solids.append(Solid(id=p["id"], name=str(p.get("type") or "part"), type="part",
                            color=(0.62, 0.60, 0.58), manifold=None, verts=v, tris=t))
        los.append(v.min(0))
        his.append(v.max(0))
    if not solids:
        return None
    lo, hi = np.min(los, 0), np.max(his, 0)
    bbox = (float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2]))
    longest = float((hi - lo).max()) or 1.0
    kind = "product" if longest < 3.0 else "exterior"
    cam = orbit_camera(bbox, elev_deg=26.0 if kind == "product" else 18.0)
    rgb, depth, nrm, idbuf, hotspots = render(solids, cam, W=width, H=height)
    coverage = float(np.count_nonzero(idbuf >= 0)) / idbuf.size
    if coverage < 0.01:
        return None
    return _to_png(rgb), _to_png(depth), _to_png(nrm), hotspots, kind


async def render_parts(parts, *, width: int = 1200, height: int = 800,
                       finish: bool = True, style: str | None = None) -> RenderResult | None:
    """Render a decomposed mesh (list of parts) with PER-PART hotspots — each
    part is individually selectable. Same finish path as render_mesh (Tier 2)."""
    try:
        built = await asyncio.to_thread(_raster_parts, parts, width, height)
    except Exception as exc:  # noqa: BLE001
        logger.warning("parts raster failed: %s", exc)
        return None
    if not built:
        return None
    base_png, depth_png, normal_png, hotspots, kind = built

    image_bytes, provider, finished = base_png, "katha-mesh", False
    if finish:
        graph = {"design_type": kind, "style": {"primary": style} if style else {}}
        try:
            res = await finish_render(base_png, depth_png, build_finish_prompt(graph, kind=kind))
        except Exception as exc:  # noqa: BLE001
            logger.warning("parts finish failed: %s", exc)
            res = None
        if res:
            image_bytes = res["bytes"]
            provider = f"katha-mesh+{res['provider']}"
            finished = True

    return RenderResult(
        image_bytes=image_bytes, hotspots=hotspots, base_bytes=base_png,
        depth_bytes=depth_png, normal_bytes=normal_png, provider=provider,
        kind=kind, finished=finished,
    )
