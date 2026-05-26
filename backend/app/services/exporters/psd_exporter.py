"""PSD exporter — 2D plan view, layer per object grouped by space.

The whole point of exporting PSD over PNG is **layers**. Architects use
Photoshop to assemble presentation boards on top of their plans —
labelling rooms, swapping material swatches, adding annotations,
combining views. A flat composite they could screenshot.

What we ship:
  · A top-down 2D plan view of the room
  · One group per space (named after room.type, e.g. "Kitchen")
  · One layer per furnishing inside its space group, named by object id
  · Each furnishing layer is a coloured rectangle for the object's
    top-down footprint (length × width at position x,z), tinted by the
    object's material
  · A "Floor" layer underneath showing the room outline
  · A "Title" group with project name + dimensions text

Pixel density is 100 px/m. A typical 6 × 4.5 m kitchen becomes a
~720 × 600 px PSD plus margins — easy for Photoshop, small payload.

Matches the layer schemes of the IFC and Rhino exporters: space-then-
object, so an architect carries one mental model across all three.

Future v2 enhancements (deliberately out of scope):
  · Composite render as a base layer (needs the AI image-gen output
    to be ready at export time)
  · Orthographic projections (front / side elevations) as separate
    layers
  · Dimensioning + grid lines
"""

from __future__ import annotations

import io
from typing import Any

try:
    from psd_tools import PSDImage
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    PSDImage = None
    Image = None
    ImageDraw = None
    ImageFont = None


_PX_PER_M = 100  # rendering density — 6×4.5m room becomes ~600×450px footprint
_MARGIN_PX = 60
_TITLE_BAND_PX = 80
_PAPER_COLOR = (248, 244, 234)        # cream paper
_FLOOR_COLOR = (235, 230, 218)        # subtle ivory
_FLOOR_STROKE = (90, 84, 70)          # ink-ish edge
_FURNISHING_DEFAULT = (180, 158, 122)  # warm timber
_TEXT_COLOR = (40, 36, 32)


# Fonts present in most Linux deploys + macOS dev boxes. Pillow's
# default bitmap font is unreadable at our title size, so we try a
# few standard installs first and fall back gracefully.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _m(value: Any) -> float:
    """Coerce a length to metres (matches obj_exporter convention).
    Values > 20 are interpreted as millimetres."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _hex_to_rgb(value: Any, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(value, str):
        return fallback
    v = value.lstrip("#")
    if len(v) != 6:
        return fallback
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return fallback


def _safe_name(name: str) -> str:
    return (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-")
        or "project"
    )


def _load_title_font(size_px: int = 22):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_floor_layer_image(canvas_w: int, canvas_h: int, room_w_px: int,
                            room_h_px: int, ox: int, oy: int) -> "Image.Image":
    """A canvas-sized transparent layer with the room footprint drawn at
    (ox, oy) → (ox + room_w_px, oy + room_h_px). We render full-canvas
    rather than a cropped image so PSD layer bboxes align cleanly with
    the rest of the plan layers."""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [ox, oy, ox + room_w_px - 1, oy + room_h_px - 1],
        fill=_FLOOR_COLOR + (255,),
        outline=_FLOOR_STROKE + (255,),
        width=2,
    )
    return img


def _make_furnishing_layer_image(canvas_w: int, canvas_h: int, x: int, y: int,
                                 w_px: int, h_px: int, fill: tuple[int, int, int],
                                 label: str) -> "Image.Image":
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if w_px > 0 and h_px > 0:
        draw.rectangle(
            [x, y, x + w_px - 1, y + h_px - 1],
            fill=fill + (235,),
            outline=tuple(max(0, c - 35) for c in fill) + (255,),
            width=1,
        )
        # Object id label inside the rectangle when it's wide enough.
        if w_px >= 70 and h_px >= 20:
            try:
                small = _load_title_font(11)
                draw.text((x + 4, y + 4), label[:24], fill=_TEXT_COLOR, font=small)
            except Exception:  # noqa: BLE001
                pass
    return img


def _make_title_layer_image(canvas_w: int, room_l_m: float, room_w_m: float,
                            project_name: str) -> "Image.Image":
    img = Image.new("RGBA", (canvas_w, _TITLE_BAND_PX), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    title_font = _load_title_font(22)
    sub_font = _load_title_font(12)
    draw.text((_MARGIN_PX, 16), project_name, fill=_TEXT_COLOR, font=title_font)
    sub = f"PLAN · {room_l_m:.2f} × {room_w_m:.2f} m · 1 cm = 1 m at 100 dpi"
    draw.text((_MARGIN_PX, 48), sub, fill=tuple(c + 60 for c in _TEXT_COLOR), font=sub_font)
    # Title rule under the text
    draw.line(
        [_MARGIN_PX, _TITLE_BAND_PX - 8, canvas_w - _MARGIN_PX, _TITLE_BAND_PX - 8],
        fill=_FLOOR_STROKE + (255,),
        width=1,
    )
    return img


def export(spec: dict, graph: dict) -> dict:
    if PSDImage is None or Image is None:
        raise RuntimeError("psd-tools / Pillow not installed; cannot export PSD")

    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"

    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    room_type = (room.get("type") or "Room").strip() or "Room"
    room_dims = room.get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)

    # Canvas — room footprint + margin all around + title band at top.
    room_px_l = int(room_l * _PX_PER_M)
    room_px_w = int(room_w * _PX_PER_M)
    canvas_w = room_px_l + _MARGIN_PX * 2
    canvas_h = room_px_w + _MARGIN_PX * 2 + _TITLE_BAND_PX
    plan_origin_y = _TITLE_BAND_PX + _MARGIN_PX  # y-coord of room top edge

    # Material colour lookup
    mat_color: dict[str, tuple[int, int, int]] = {}
    for mat in graph.get("materials") or []:
        mid = mat.get("id") or mat.get("name")
        if mid:
            mat_color[str(mid)] = _hex_to_rgb(mat.get("color"), _FURNISHING_DEFAULT)

    psd = PSDImage.new(mode="RGB", size=(canvas_w, canvas_h), color=_PAPER_COLOR)

    # ── Floor ───────────────────────────────────────────────────
    floor_img = _make_floor_layer_image(
        canvas_w, canvas_h, room_px_l, room_px_w, _MARGIN_PX, plan_origin_y,
    )
    psd.create_pixel_layer(floor_img, name="Floor")

    # ── Furnishings — one layer per object inside a room group ──
    space_group_name = room_type.upper()[:40] or "FURNISHINGS"
    space_group = psd.create_group(name=space_group_name)

    for obj in graph.get("objects") or []:
        otype = (obj.get("type") or "object").lower()
        oid = str(obj.get("id") or otype)

        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}

        # Plan view uses KATHA x (width) and z (depth)
        l = _m(d.get("length")) or 0.4
        wd = _m(d.get("width")) or 0.4

        cx_m = float(pos.get("x", 0.0))
        cz_m = float(pos.get("z", 0.0))

        # Object center → top-left in PSD pixel coords
        x_px = _MARGIN_PX + int((cx_m - l / 2) * _PX_PER_M)
        y_px = plan_origin_y + int((cz_m - wd / 2) * _PX_PER_M)
        w_px = max(int(l * _PX_PER_M), 4)
        h_px = max(int(wd * _PX_PER_M), 4)

        fill = mat_color.get(obj.get("material") or "", _FURNISHING_DEFAULT)

        layer_img = _make_furnishing_layer_image(
            canvas_w, canvas_h, x_px, y_px, w_px, h_px, fill, oid,
        )
        layer = psd.create_pixel_layer(layer_img, name=oid)
        # Reparent into the space group (psd-tools doesn't offer a
        # "create inside group" helper — remove + append is the
        # documented pattern).
        psd.remove(layer)
        space_group.append(layer)

    # ── Title group (drawn on top) ─────────────────────────────
    title_group = psd.create_group(name="TITLE")
    title_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    title_img.paste(
        _make_title_layer_image(canvas_w, room_l, room_w, project_name),
        (0, 0),
    )
    title_layer = psd.create_pixel_layer(title_img, name="Project")
    psd.remove(title_layer)
    title_group.append(title_layer)

    buf = io.BytesIO()
    psd.save(buf)
    return {
        "content_type": "image/vnd.adobe.photoshop",
        "filename": f"{_safe_name(project_name)}-plan.psd",
        "bytes": buf.getvalue(),
    }
