"""PDF importer — minimal stdlib text + dimension extraction.

Parses uncompressed text streams from a PDF byte payload (no OCR, no
external dependency). Most PDFs produced by CAD/architecture tools
include text streams; scanned PDFs degrade to a 'no text streams
present' warning. Dimensions are detected by regex on the recovered
text (`L × W × H`, `mm`, `cm`, feet/inches).
"""

from __future__ import annotations

import re
import zlib
from typing import Any


_DIM_RE = re.compile(
    r"(\d{1,4}(?:\.\d+)?)\s*(?:[x×X]|by)\s*(\d{1,4}(?:\.\d+)?)"
    r"(?:\s*(?:[x×X]|by)\s*(\d{1,4}(?:\.\d+)?))?\s*(mm|cm|m|ft|in)?",
    re.IGNORECASE,
)


def _decode_streams(payload: bytes) -> str:
    """Pull text from `BT ... ET` blocks, decompressing FlateDecode streams."""
    out: list[str] = []
    # 1. Direct text-show operators in unencoded streams.
    for m in re.finditer(rb"\((.*?)\)\s*Tj", payload, flags=re.DOTALL):
        try:
            out.append(m.group(1).decode("latin-1", errors="ignore"))
        except Exception:
            continue
    # 2. Flate-decoded streams.
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", payload, flags=re.DOTALL):
        chunk = m.group(1)
        try:
            decoded = zlib.decompress(chunk)
        except zlib.error:
            continue
        for tm in re.finditer(rb"\((.*?)\)\s*Tj", decoded, flags=re.DOTALL):
            try:
                out.append(tm.group(1).decode("latin-1", errors="ignore"))
            except Exception:
                continue
    return "\n".join(out)


def _detect_pages(payload: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", payload))


def _detect_dimensions(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _DIM_RE.finditer(text):
        a, b, c, unit = m.group(1), m.group(2), m.group(3), (m.group(4) or "").lower()
        out.append({
            "raw": m.group(0).strip(),
            "values": [float(a), float(b)] + ([float(c)] if c else []),
            "unit": unit or "unknown",
        })
        if len(out) >= 25:
            break
    return out


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    pages = _detect_pages(payload)
    text = _decode_streams(payload)
    text = re.sub(r"\s+", " ", text).strip()
    dims = _detect_dimensions(text)
    warnings: list[str] = []
    if not text:
        warnings.append(
            "No text streams recovered. PDF may be image-only / scanned — "
            "OCR not available in this importer."
        )
    return {
        "format": "pdf",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"PDF: {pages} page(s); {len(text):,} chars of text; "
            f"{len(dims)} dimension hint(s)."
        ),
        "extracted": {
            "page_count": pages,
            "text_excerpt": text[:2000],
            "dimensions": dims,
        },
        "warnings": warnings,
    }
