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
from PIL import Image, ImageFilter

from app.config import get_settings
from app.services.spatial.finish import build_finish_prompt, finish_render
from app.services.spatial.kernel import Solid, _room_dims, build_scene
from app.services.spatial.presentation import build_presentation_prompt
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


def _hero_interior_camera(solids, bbox):
    """Eye-level interior HERO camera — stands ~1.5 m off a front corner and looks
    ACROSS the space at eye height (not the top-down dollhouse), so a presentation
    render reads like real interior photography. Returns ``(cam, cull_ids)``: the
    structural walls sitting between the eye and the scene centre are culled by
    geometry (works for multi-room, which carries no wall side-tags) so the view
    sees INTO the space instead of the back of a wall — an eye-level cutaway."""
    lo, hi = np.asarray(bbox[:3], float), np.asarray(bbox[3:], float)
    center = (lo + hi) / 2.0
    size = hi - lo
    diag = float(np.hypot(size[0], size[2])) or 3.0
    eye_h = lo[1] + float(min(1.6, max(1.2, size[1] * 0.6)))     # ~1.5 m eye level
    az = np.radians(38.0)
    dirn = np.array([np.cos(az), 0.0, np.sin(az)])
    eye = np.array([center[0] + dirn[0] * diag * 1.12, eye_h,
                    center[2] + dirn[2] * diag * 1.12])
    target = np.array([center[0], lo[1] + float(min(1.3, size[1] * 0.5)), center[2]])
    cam = dict(eye=eye, target=target, fov=58.0, near=0.05, far=diag * 12)
    view = eye - center
    vv = float(np.dot(view, view)) or 1.0
    cull: set = set()
    for s in solids:
        if s.type == "wall" and s.verts is not None and len(s.verts):
            c = s.verts.mean(0)
            if float(np.dot(c - center, view)) > 0.10 * vv:        # wall is in front of the eye
                cull.add(s.id)
    return cam, cull


def _build_and_raster(graph: dict, width: int, height: int, ss: int = 2, hero: bool = False):
    """CPU-bound: kernel + camera + rasterise. Runs in a worker thread. ``ss`` is
    the anti-aliasing oversample factor. ``hero=True`` selects eye-level cameras
    (for presentation renders) instead of the technical dollhouse/aerial views."""
    solids, bbox, kind = build_scene(graph)
    floor_count = sum(1 for s in solids if s.type == "floor")
    # Meaningful to show if there's furniture OR it's a multi-room plan (the
    # rooms themselves are the subject, even before they're furnished).
    if not any(s.type not in _STRUCTURAL for s in solids) and floor_count < 2:
        return None

    if hero and kind == "interior":
        # Presentation: eye-level interior instead of the top-down dollhouse.
        cam, cull_ids = _hero_interior_camera(solids, bbox)
        render_solids = [s for s in solids if s.id not in cull_ids]
    elif hero:
        # Presentation exterior: a LOW, eye-level three-quarter view in the
        # landscape (the reference look), not the aerial technical framing.
        non_ground = [s for s in solids if s.type != "ground" and s.verts is not None and len(s.verts)]
        lo = np.min([s.verts.min(0) for s in non_ground], 0)
        hi = np.max([s.verts.max(0) for s in non_ground], 0)
        cam = orbit_camera((lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]),
                           azimuth_deg=35.0, elev_deg=12.0, dist_factor=2.5, fov=48.0)
        render_solids = solids
    elif kind == "interior" and floor_count >= 2:
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

    rgb, depth, nrm, idbuf, hotspots = render(render_solids, cam, W=width, H=height, ss=ss)
    coverage = float(np.count_nonzero(idbuf >= 0)) / idbuf.size
    if coverage < 0.02:  # camera saw essentially nothing — let the caller fall back
        logger.warning("spatial render coverage too low (%.3f) kind=%s", coverage, kind)
        return None
    # idbuf holds the render-order index of the solid at each pixel; the id list
    # (index-aligned) lets a caller build a per-object mask (localized editing).
    return (_to_png(rgb), _to_png(depth), _to_png(nrm), hotspots, kind,
            idbuf, [s.id for s in render_solids])


async def render_design(graph: dict, *, width: int = 1200, height: int = 800,
                        finish: bool = True, presentation: bool = False,
                        mood: dict | None = None) -> RenderResult | None:
    """Spec → RenderResult, or None to signal the caller to use the legacy path.

    ``presentation=True`` produces the hero/"storefront" image — an atmospheric,
    styled architectural photograph (see ``presentation.build_presentation_prompt``)
    rather than the faithful technical clay render. It ALLOWS the img2img finish so
    it renders a photoreal frame today; a Replicate token upgrades it to
    depth-locked ControlNet (faithful photoreal). ``mood`` tunes the look."""
    settings = get_settings()
    ss = max(1, int(getattr(settings, "spatial_render_supersample", 2) or 1))
    faithful_only = bool(getattr(settings, "spatial_render_faithful_only", True))
    try:
        built = await asyncio.to_thread(_build_and_raster, graph, width, height, ss, presentation)
    except Exception as exc:  # noqa: BLE001 — geometry must never break generation
        logger.warning("spatial kernel/raster failed: %s", exc)
        return None
    if not built:
        return None
    base_png, depth_png, normal_png, hotspots, kind, _idbuf, _solid_ids = built

    image_bytes, provider, finished = base_png, "katha-kernel", False
    if finish:
        try:
            if presentation:
                # PRESENTATION (hero) render — the styling/mood prompt, and the
                # atmospheric img2img finish is ALLOWED (geometry_locked_only=False)
                # so a photoreal frame renders now. ControlNet-depth still wins when
                # a Replicate token is set, making it faithful-photoreal.
                res = await finish_render(
                    base_png, depth_png,
                    build_presentation_prompt(graph, kind=kind, mood=mood),
                    geometry_locked_only=False,
                )
            else:
                # geometry_locked_only: only a depth-locked finish (ControlNet-depth)
                # may replace the exact kernel render — it stays faithful to the model.
                # Without a Replicate token this returns None and we serve the clay
                # render, which matches the plan / 3D / drawings exactly. The img2img
                # "beautify" (Gemini/gpt-image-1) is deliberately never used here
                # (unless spatial_render_faithful_only is off): it re-imagines the
                # scene and drifts from the real geometry.
                res = await finish_render(
                    base_png, depth_png,
                    build_finish_prompt(graph, kind=kind),
                    geometry_locked_only=faithful_only,
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


def _feathered_object_mask(idbuf, solid_ids, object_ids, target_wh,
                           grow: int = 23, blur: int = 8):
    """A 0..1 blend weight (target size): 1 over the given objects' pixels
    (dilated + feathered so the composite has no hard seam), 0 elsewhere. The
    id-buffer shares the render's camera, so the mask lands exactly on the
    objects; the dilation is generous so the finish's generative overflow beyond
    the geometry silhouette (and the object's OLD pixels in the base image) are
    covered too. Returns None when none of the objects are visible in frame."""
    wanted = set(object_ids)
    sel = np.zeros(idbuf.shape, dtype=bool)
    for oi, sid in enumerate(solid_ids):
        if sid in wanted:
            sel |= (idbuf == oi)
    if not sel.any():
        return None
    m = Image.fromarray((sel * 255).astype(np.uint8), "L")
    if grow:
        m = m.filter(ImageFilter.MaxFilter(grow if grow % 2 else grow + 1))
    if blur:
        m = m.filter(ImageFilter.GaussianBlur(blur))
    if m.size != tuple(target_wh):
        m = m.resize(tuple(target_wh))
    return (np.asarray(m, np.float32) / 255.0)[..., None]


async def render_design_localized(
    graph: dict, prev_finished: bytes, changed_ids: list[str],
    *, width: int = 1200, height: int = 800,
) -> RenderResult | None:
    """Localized edit render: re-finish the new spec, but composite ONLY the
    changed objects' region over the PREVIOUS finished image — so an edit changes
    just that part of the hero and the rest stays pixel-identical (no whole-scene
    drift). Requires two things to be sound: geometry unchanged (the caller
    checks, so the new render shares the previous camera) AND a geometry-locked
    finish (ControlNet-depth — see the provider check below), so the object sits
    at its exact geometry position in both renders and the mask aligns. Returns
    None — caller falls back to a full render — when the scene can't raster, the
    finish isn't geometry-locked/available, or the changed object isn't in view."""
    if not prev_finished or not changed_ids:
        return None
    try:
        built = await asyncio.to_thread(_build_and_raster, graph, width, height)
    except Exception as exc:  # noqa: BLE001 — never break the render path
        logger.warning("localized raster failed: %s", exc)
        return None
    if not built:
        return None
    base_png, depth_png, normal_png, hotspots, kind, idbuf, solid_ids = built

    res = await finish_render(base_png, depth_png, build_finish_prompt(graph, kind=kind),
                              geometry_locked_only=True)
    if not res or not res.get("bytes"):
        return None  # no geometry-locked finish → let the caller do a normal render
    # Localized compositing needs a GEOMETRY-LOCKED finish. ControlNet-depth
    # conditions on the kernel depth map, so every object renders at its exact
    # geometry position — the clay-derived mask lands on it in both the previous
    # and the new render, and the paste is seamless. The img2img providers
    # (Gemini, gpt-image-1) re-imagine the frame each run: they rearrange and even
    # invent furniture, so an object's finished pixels drift from its geometry
    # position and the mask no longer aligns with the PREVIOUS render (pasting the
    # new region onto the wrong spot). So localized editing only engages under
    # ControlNet-depth; otherwise defer to a full render (today's behaviour). All
    # the plumbing is live — it turns on the moment a replicate_api_token is set.
    prov = str(res.get("provider") or "")
    if "controlnet" not in prov:
        logger.info("localized edit needs a geometry-locked finish; got %s — full render", prov)
        return None
    new_fin = Image.open(io.BytesIO(res["bytes"])).convert("RGB")
    prev = Image.open(io.BytesIO(prev_finished)).convert("RGB")
    if prev.size != new_fin.size:
        prev = prev.resize(new_fin.size)

    w = _feathered_object_mask(idbuf, solid_ids, changed_ids, new_fin.size)
    if w is None:
        return None  # changed object not visible → a full render is the honest result
    comp = np.asarray(prev, np.float32) * (1.0 - w) + np.asarray(new_fin, np.float32) * w
    out = _to_png(comp / 255.0)

    return RenderResult(
        image_bytes=out, hotspots=hotspots, base_bytes=base_png,
        depth_bytes=depth_png, normal_bytes=normal_png,
        provider=f"katha-kernel+{res['provider']}+localized", kind=kind, finished=True,
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
            # Faithful to the uploaded model: only a depth-locked finish may
            # replace the clay render (see render_design). Without a token we show
            # the exact imported geometry, not an img2img reinterpretation of it.
            res = await finish_render(base_png, depth_png,
                                      build_finish_prompt(graph, kind=kind),
                                      geometry_locked_only=True)
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
