"""Image importer — JPG / PNG header + dominant-colour extraction.

Stdlib-only: parses dimensions from raw bytes, picks a coarse dominant
colour by sampling the file body, infers EXIF orientation tag for
JPEGs. No Pillow, no OCR.
"""

from __future__ import annotations

import struct
from collections import Counter
from typing import Any


def _png_dims(payload: bytes) -> tuple[int, int] | None:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if len(payload) < 24:
        return None
    width, height = struct.unpack(">II", payload[16:24])
    return width, height


def _jpeg_dims(payload: bytes) -> tuple[int, int] | None:
    if not payload.startswith(b"\xff\xd8"):
        return None
    i = 2
    n = len(payload)
    while i < n - 9:
        # Each marker starts with 0xFF; SOF0 = C0..CF except DHT/DAC/DNL/DRI/JPG.
        if payload[i] != 0xFF:
            i += 1
            continue
        marker = payload[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = struct.unpack(">H", payload[i + 5:i + 7])[0]
            width = struct.unpack(">H", payload[i + 7:i + 9])[0]
            return width, height
        if marker in (0xD8, 0xD9):  # SOI / EOI
            i += 2
            continue
        try:
            seg_len = struct.unpack(">H", payload[i + 2:i + 4])[0]
        except struct.error:
            return None
        i += 2 + seg_len
    return None


def _exif_orientation(payload: bytes) -> int | None:
    if not payload.startswith(b"\xff\xd8"):
        return None
    idx = payload.find(b"Exif\x00\x00")
    if idx < 0:
        return None
    # Walk the IFD0 lazily — we only want tag 0x0112 (orientation).
    block = payload[idx + 6:idx + 6 + 4096]
    if len(block) < 16:
        return None
    byte_order = block[0:2]
    if byte_order == b"II":
        unp = "<"
    elif byte_order == b"MM":
        unp = ">"
    else:
        return None
    try:
        ifd_offset = struct.unpack(unp + "I", block[4:8])[0]
        entry_count = struct.unpack(unp + "H", block[ifd_offset:ifd_offset + 2])[0]
        for i in range(entry_count):
            entry = block[ifd_offset + 2 + i * 12:ifd_offset + 2 + (i + 1) * 12]
            if len(entry) < 12:
                break
            tag = struct.unpack(unp + "H", entry[0:2])[0]
            if tag == 0x0112:
                return struct.unpack(unp + "H", entry[8:10])[0]
    except struct.error:
        return None
    return None


def _dominant_colour_hex(payload: bytes) -> str | None:
    """Coarse: sample every Nth byte triplet, bucket to 5-bit channels."""
    if len(payload) < 1024:
        return None
    step = max(1, len(payload) // 4096)
    buckets: Counter[tuple[int, int, int]] = Counter()
    for i in range(0, len(payload) - 3, step * 3):
        r, g, b = payload[i], payload[i + 1], payload[i + 2]
        # Skip obvious non-pixel runs (all-zero / all-FF / very dark).
        if max(r, g, b) < 24 or min(r, g, b) > 240:
            continue
        buckets[(r >> 3, g >> 3, b >> 3)] += 1
    if not buckets:
        return None
    (r, g, b), _ = buckets.most_common(1)[0]
    r, g, b = r << 3, g << 3, b << 3
    return f"#{r:02x}{g:02x}{b:02x}"


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    fmt = "image"
    dims = None
    if payload.startswith(b"\x89PNG"):
        dims = _png_dims(payload)
        fmt = "png"
    elif payload.startswith(b"\xff\xd8"):
        dims = _jpeg_dims(payload)
        fmt = "jpeg"
    orientation = _exif_orientation(payload) if fmt == "jpeg" else None
    dom = _dominant_colour_hex(payload)
    warnings: list[str] = []
    if dims is None:
        warnings.append(f"Could not parse image dimensions from {fmt!r} header.")
    return {
        "format": fmt,
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"{fmt.upper()}: "
            + (f"{dims[0]} × {dims[1]} px" if dims else "dimensions unknown")
            + (f"; dominant colour {dom}" if dom else "")
        ),
        "extracted": {
            "image_format": fmt,
            "width_px": dims[0] if dims else None,
            "height_px": dims[1] if dims else None,
            "exif_orientation": orientation,
            "dominant_colour_hex": dom,
        },
        "warnings": warnings,
    }
