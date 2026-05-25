"""PSD importer — Photoshop file header + layer count, stdlib only.

Photoshop is universal in architecture (85-90% adoption in every region
of the Global Market deck). Architects deliver presentations, mood
boards, and finished renders as PSDs — so even a metadata-only importer
unlocks the "Import from any software" promise for the most-used tool
in our market.

The Adobe Photoshop File Format Specification fixes the first 26 bytes
of every PSD (header) and prefixes the four major sections with their
byte length. We parse:

  - Header → version (PSD/PSB), channels, dimensions, bit depth, colour mode
  - Image Resources → DPI (pixel density resource 0x03ED)
  - Layer & Mask Info → layer count

Layer NAMES live in additional-info blocks keyed `luni` (Unicode) — a
~150-line byte walk that we deliberately skip in this importer. The
header data alone gives an architect a meaningful one-line summary of
what they uploaded; the original payload is preserved for downstream
tools that can render it.

PSB (large-document format, version 2) uses 8-byte length prefixes for
the layer/mask section instead of 4-byte. We branch on that.
"""

from __future__ import annotations

import struct
from typing import Any

_PSD_MAGIC = b"8BPS"

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


def _parse_header(payload: bytes) -> dict[str, Any] | None:
    if len(payload) < 26 or not payload.startswith(_PSD_MAGIC):
        return None
    try:
        version = struct.unpack(">H", payload[4:6])[0]
        # bytes 6..11 reserved (zeros) per spec — don't validate
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
        # Pascal-style name (length byte + name, padded to even length).
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
            # ResolutionInfo: hRes (4 bytes fixed-point 16.16), hResUnit (2),
            # widthUnit (2), vRes (4 fixed-point), vResUnit (2), heightUnit (2)
            try:
                h_fixed = struct.unpack(">I", data[0:4])[0]
                v_fixed = struct.unpack(">I", data[8:12])[0]
                h_dpi = h_fixed / 65536.0
                v_dpi = v_fixed / 65536.0
            except struct.error:
                pass
        # Advance — data is padded to even length.
        block = data_start + 4 + data_len
        if block % 2:
            block += 1
        if block <= i:
            break
        i = block
    return h_dpi, v_dpi


def _layer_count(payload: bytes, offset: int, is_psb: bool) -> tuple[int | None, int]:
    """Read the layer count from the Layer & Mask Information section.

    Returns (count, next_offset). count is None if the section is empty
    or malformed. next_offset is provided so the caller could continue,
    though we don't use it.
    """
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
    # Layer info subsection — itself length-prefixed.
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
    # Negative count means the first alpha channel is transparency data.
    return abs(raw), offset + size_width + section_len


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    warnings: list[str] = []
    header = _parse_header(payload)
    if header is None:
        return {
            "format": "psd",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Not a valid PSD/PSB file (bad header).",
            "extracted": {},
            "warnings": ["Header signature '8BPS' missing or file truncated."],
        }

    is_psb = header["is_psb"]
    h_dpi: float | None = None
    v_dpi: float | None = None
    layers: int | None = None

    try:
        # Skip Color Mode Data section: 4-byte length, then that many bytes.
        i = 26
        if i + 4 > len(payload):
            raise ValueError("truncated after header")
        color_mode_len = struct.unpack(">I", payload[i:i + 4])[0]
        i += 4 + color_mode_len

        # Image Resources section: 4-byte length, then that many bytes.
        if i + 4 > len(payload):
            raise ValueError("truncated before image resources")
        img_res_len = struct.unpack(">I", payload[i:i + 4])[0]
        img_res = payload[i + 4:i + 4 + img_res_len]
        h_dpi, v_dpi = _read_dpi(img_res)
        i += 4 + img_res_len

        # Layer & Mask Information section.
        layers, _next = _layer_count(payload, i, is_psb)
    except (ValueError, struct.error) as exc:
        warnings.append(f"Section walk stopped: {exc}")

    color_mode = header["color_mode"]
    ver_label = "PSB" if is_psb else "PSD"
    summary = (
        f"{ver_label}: {header['width_px']} × {header['height_px']} px, "
        f"{color_mode} {header['bit_depth']}-bit, "
        f"{header['channels']} channel(s)"
        + (f", {layers} layer(s)" if layers is not None else "")
        + (f"; {h_dpi:.0f} dpi" if h_dpi else "")
        + "."
    )

    return {
        "format": "psb" if is_psb else "psd",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": summary,
        "extracted": {
            "version": ver_label,
            "width_px": header["width_px"],
            "height_px": header["height_px"],
            "channels": header["channels"],
            "bit_depth": header["bit_depth"],
            "color_mode": color_mode,
            "color_mode_id": header["color_mode_id"],
            "layer_count": layers,
            "horizontal_dpi": round(h_dpi, 2) if h_dpi else None,
            "vertical_dpi": round(v_dpi, 2) if v_dpi else None,
        },
        "warnings": warnings,
    }
