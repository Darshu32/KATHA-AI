"""PSD importer — Photoshop file header + layer tree + thumbnail.

Photoshop is universal in architecture (85-90% adoption in every region
of the Global Market deck). Architects deliver presentations, mood
boards, and finished renders as PSDs — and the *layer names* are
where the architectural meaning lives: GRID-A · WALLS · ELEVATION ·
KITCHEN · LIGHTING · FFL +0.000. Surfacing them in the import summary
turns a generic "1920 × 1080 RGB, 17 layers" line into something an
architect can scan.

Two paths:

  1. psd-tools (preferred) — walks the full layer tree (groups +
     pixel + type + shape layers), surfaces names + visibility +
     opacity + per-layer bounding boxes, and renders an embedded
     thumbnail at <= 256 px.
  2. Stdlib header parser (fallback) — runs when psd-tools is
     missing or rejects the file. Returns the same shape minus the
     layer tree and thumbnail.

The fallback exists because real PSDs from buggy plugins or older
Photoshop releases sometimes break psd-tools' parser but still expose
a valid 8BPS header — we'd rather show coarse metadata than refuse.

PSB (large-document format, version 2) is supported by both paths
through the same code (psd-tools handles it natively; the stdlib
section walk branches on the 4-byte vs 8-byte length prefix).
"""

from __future__ import annotations

import base64
import io
import logging
import struct
from typing import Any

try:
    from psd_tools import PSDImage
    from psd_tools.constants import ColorMode as _PSDColorMode
except Exception:  # noqa: BLE001
    PSDImage = None
    _PSDColorMode = None

try:
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

logger = logging.getLogger(__name__)

_PSD_MAGIC = b"8BPS"
_THUMBNAIL_MAX_EDGE = 256
_THUMBNAIL_QUALITY = 80

_COLOR_MODES = {
    0: "Bitmap",
    1: "Grayscale",
    2: "Indexed",
    3: "RGB",
    4: "CMYK",
    7: "Multichannel",
    8: "Duotone",
    9: "Lab",
}


# ── Path A — psd-tools (rich) ──────────────────────────────────────


def _color_mode_label(mode_value: Any) -> tuple[str, int | None]:
    """psd-tools returns an enum; the stdlib path returns an int."""
    try:
        mode_id = int(mode_value)
    except (TypeError, ValueError):
        return f"unknown({mode_value})", None
    return _COLOR_MODES.get(mode_id, f"unknown({mode_id})"), mode_id


def _layer_node(layer, depth: int) -> dict[str, Any]:
    bbox = None
    try:
        if layer.bbox:
            l, t, r, b = layer.bbox
            # Empty layers come back as (0,0,0,0) — return None so
            # the consumer can tell "no pixels" from "untouched".
            if (r - l) > 0 or (b - t) > 0:
                bbox = {"left": int(l), "top": int(t), "right": int(r), "bottom": int(b)}
    except Exception:  # noqa: BLE001
        pass
    return {
        "name": str(getattr(layer, "name", "") or ""),
        "kind": str(getattr(layer, "kind", "") or ""),
        "visible": bool(getattr(layer, "visible", True)),
        "opacity": int(getattr(layer, "opacity", 255) or 0),
        "depth": depth,
        "bbox": bbox,
    }


def _walk_layers(psd) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def recurse(node, depth: int) -> None:
        for child in node:
            out.append(_layer_node(child, depth))
            if getattr(child, "is_group", lambda: False)():
                recurse(child, depth + 1)
            # Hard ceiling — pathological files can have thousands of
            # layers; the import summary doesn't need all of them.
            if len(out) >= 200:
                return

    recurse(psd, 0)
    return out


def _render_thumbnail(psd) -> str | None:
    """Best-effort base64-encoded PNG thumbnail at <= 256 px.

    Returns None when neither an embedded thumbnail/preview is
    available nor a composite can be rendered without errors.
    """
    if Image is None:
        return None

    pil: "Image.Image | None" = None
    try:
        if psd.has_thumbnail():
            pil = psd.thumbnail
    except Exception:  # noqa: BLE001
        pil = None
    if pil is None:
        try:
            pil = psd.composite()
        except Exception:  # noqa: BLE001
            pil = None
    if pil is None:
        return None

    try:
        # Composite returns a PIL image already; resize to bound the
        # outgoing payload. Keep aspect ratio.
        pil.thumbnail((_THUMBNAIL_MAX_EDGE, _THUMBNAIL_MAX_EDGE))
        # Force RGB for JPEG output; PSDs in CMYK / Lab won't encode.
        if pil.mode not in ("RGB", "L"):
            pil = pil.convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=_THUMBNAIL_QUALITY)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def _parse_via_psdtools(payload: bytes) -> dict[str, Any] | None:
    if PSDImage is None:
        return None
    try:
        psd = PSDImage.open(io.BytesIO(payload))
    except Exception:  # noqa: BLE001
        return None

    color_mode_label, color_mode_id = _color_mode_label(psd.color_mode)
    layers = _walk_layers(psd)
    layer_count = len(layers)
    leaf_count = sum(1 for l in layers if l["kind"] != "group")
    group_count = sum(1 for l in layers if l["kind"] == "group")

    version = int(psd.version)
    is_psb = version == 2

    thumbnail_b64 = _render_thumbnail(psd)

    # DPI lives in image_resources resource 0x03ED. psd-tools exposes
    # the raw resources dict; the stdlib helper does this already, so
    # we reuse it on the raw payload to stay consistent.
    h_dpi, v_dpi = _read_dpi_safely(payload)

    return {
        "version": "PSB" if is_psb else "PSD",
        "is_psb": is_psb,
        "width_px": int(psd.width),
        "height_px": int(psd.height),
        "channels": int(psd.channels),
        "bit_depth": int(psd.depth),
        "color_mode": color_mode_label,
        "color_mode_id": color_mode_id,
        "layer_count": layer_count,
        "leaf_layer_count": leaf_count,
        "group_count": group_count,
        "layers": layers,
        "horizontal_dpi": round(h_dpi, 2) if h_dpi else None,
        "vertical_dpi": round(v_dpi, 2) if v_dpi else None,
        "thumbnail_b64": thumbnail_b64,
        "thumbnail_mime": "image/jpeg" if thumbnail_b64 else None,
    }


# ── Path B — stdlib header parser (fallback) ────────────────────────


def _parse_header(payload: bytes) -> dict[str, Any] | None:
    if len(payload) < 26 or not payload.startswith(_PSD_MAGIC):
        return None
    try:
        version = struct.unpack(">H", payload[4:6])[0]
        channels = struct.unpack(">H", payload[12:14])[0]
        height = struct.unpack(">I", payload[14:18])[0]
        width = struct.unpack(">I", payload[18:22])[0]
        depth = struct.unpack(">H", payload[22:24])[0]
        color_mode = struct.unpack(">H", payload[24:26])[0]
    except struct.error:
        return None
    return {
        "version": version,
        "is_psb": version == 2,
        "channels": channels,
        "width_px": width,
        "height_px": height,
        "bit_depth": depth,
        "color_mode_id": color_mode,
        "color_mode": _COLOR_MODES.get(color_mode, f"unknown({color_mode})"),
    }


def _read_dpi(image_resources: bytes) -> tuple[float | None, float | None]:
    """Walk image resources looking for ResolutionInfo (id=0x03ED)."""
    i = 0
    n = len(image_resources)
    h_dpi: float | None = None
    v_dpi: float | None = None
    while i + 11 < n:
        if image_resources[i:i + 4] != b"8BIM":
            break
        try:
            resource_id = struct.unpack(">H", image_resources[i + 4:i + 6])[0]
        except struct.error:
            break
        if i + 6 >= n:
            break
        name_len = image_resources[i + 6]
        name_padded = name_len + 1
        if name_padded % 2:
            name_padded += 1
        data_start = i + 6 + name_padded
        if data_start + 4 > n:
            break
        try:
            data_len = struct.unpack(">I", image_resources[data_start:data_start + 4])[0]
        except struct.error:
            break
        data = image_resources[data_start + 4:data_start + 4 + data_len]
        if resource_id == 0x03ED and len(data) >= 16:
            try:
                h_fixed = struct.unpack(">I", data[0:4])[0]
                v_fixed = struct.unpack(">I", data[8:12])[0]
                h_dpi = h_fixed / 65536.0
                v_dpi = v_fixed / 65536.0
            except struct.error:
                pass
        block = data_start + 4 + data_len
        if block % 2:
            block += 1
        if block <= i:
            break
        i = block
    return h_dpi, v_dpi


def _read_dpi_safely(payload: bytes) -> tuple[float | None, float | None]:
    """Walk header → color-mode → image-resources to grab DPI, or
    return (None, None) on any structural problem."""
    try:
        i = 26
        if i + 4 > len(payload):
            return None, None
        color_mode_len = struct.unpack(">I", payload[i:i + 4])[0]
        i += 4 + color_mode_len
        if i + 4 > len(payload):
            return None, None
        img_res_len = struct.unpack(">I", payload[i:i + 4])[0]
        img_res = payload[i + 4:i + 4 + img_res_len]
        return _read_dpi(img_res)
    except (ValueError, struct.error):
        return None, None


def _layer_count(payload: bytes, offset: int, is_psb: bool) -> tuple[int | None, int]:
    """Read the layer count from the Layer & Mask Information section."""
    size_width = 8 if is_psb else 4
    if offset + size_width > len(payload):
        return None, offset
    try:
        if is_psb:
            section_len = struct.unpack(">Q", payload[offset:offset + 8])[0]
        else:
            section_len = struct.unpack(">I", payload[offset:offset + 4])[0]
    except struct.error:
        return None, offset
    if section_len == 0:
        return 0, offset + size_width
    inner = offset + size_width
    if inner + size_width > len(payload):
        return None, offset
    try:
        if is_psb:
            layer_info_len = struct.unpack(">Q", payload[inner:inner + 8])[0]
        else:
            layer_info_len = struct.unpack(">I", payload[inner:inner + 4])[0]
    except struct.error:
        return None, offset
    if layer_info_len == 0:
        return 0, inner + size_width + layer_info_len
    layer_count_offset = inner + size_width
    if layer_count_offset + 2 > len(payload):
        return None, offset
    try:
        raw = struct.unpack(">h", payload[layer_count_offset:layer_count_offset + 2])[0]
    except struct.error:
        return None, offset
    return abs(raw), offset + size_width + section_len


def _parse_via_stdlib(payload: bytes) -> dict[str, Any] | None:
    header = _parse_header(payload)
    if header is None:
        return None
    is_psb = header["is_psb"]
    h_dpi: float | None = None
    v_dpi: float | None = None
    layers: int | None = None
    try:
        i = 26
        color_mode_len = struct.unpack(">I", payload[i:i + 4])[0]
        i += 4 + color_mode_len
        img_res_len = struct.unpack(">I", payload[i:i + 4])[0]
        img_res = payload[i + 4:i + 4 + img_res_len]
        h_dpi, v_dpi = _read_dpi(img_res)
        i += 4 + img_res_len
        layers, _next = _layer_count(payload, i, is_psb)
    except (ValueError, struct.error):
        pass
    return {
        "version": "PSB" if is_psb else "PSD",
        "is_psb": is_psb,
        "width_px": header["width_px"],
        "height_px": header["height_px"],
        "channels": header["channels"],
        "bit_depth": header["bit_depth"],
        "color_mode": header["color_mode"],
        "color_mode_id": header["color_mode_id"],
        "layer_count": layers,
        "leaf_layer_count": None,
        "group_count": None,
        "layers": [],
        "horizontal_dpi": round(h_dpi, 2) if h_dpi else None,
        "vertical_dpi": round(v_dpi, 2) if v_dpi else None,
        "thumbnail_b64": None,
        "thumbnail_mime": None,
    }


# ── Entry point ─────────────────────────────────────────────────────


def _summary(parsed: dict[str, Any], parser_label: str) -> str:
    parts = [
        f"{parsed['version']}: {parsed['width_px']} × {parsed['height_px']} px",
        f"{parsed['color_mode']} {parsed['bit_depth']}-bit",
        f"{parsed['channels']} channel(s)",
    ]
    if parsed.get("layer_count") is not None:
        groups = parsed.get("group_count")
        leaves = parsed.get("leaf_layer_count")
        if groups is not None and leaves is not None:
            parts.append(f"{leaves} layer(s)" + (f" in {groups} group(s)" if groups else ""))
        else:
            parts.append(f"{parsed['layer_count']} layer(s)")
    if parsed.get("horizontal_dpi"):
        parts.append(f"{parsed['horizontal_dpi']:.0f} dpi")
    return ", ".join(parts) + f" [{parser_label}]."


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    if not payload.startswith(_PSD_MAGIC):
        return {
            "format": "psd",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Not a valid PSD/PSB file (bad header).",
            "extracted": {},
            "warnings": ["Header signature '8BPS' missing or file truncated."],
        }

    warnings: list[str] = []
    parsed = _parse_via_psdtools(payload)
    parser_label = "psd-tools"
    if parsed is None:
        parsed = _parse_via_stdlib(payload)
        parser_label = "stdlib"
        if parsed is not None:
            warnings.append(
                "psd-tools could not open this file; fell back to header-only "
                "parsing (layer names + thumbnail unavailable)."
            )

    if parsed is None:
        return {
            "format": "psd",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Could not parse PSD/PSB (header failed both parsers).",
            "extracted": {},
            "warnings": [
                "Both psd-tools and the stdlib header parser failed — the "
                "file may be truncated or written by an incompatible tool."
            ],
        }

    parsed["parser"] = parser_label
    return {
        "format": "psb" if parsed["is_psb"] else "psd",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": _summary(parsed, parser_label),
        "extracted": parsed,
        "warnings": warnings,
    }
