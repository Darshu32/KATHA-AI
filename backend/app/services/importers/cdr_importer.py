"""CorelDRAW .cdr importer — RIFF header detect + actionable redirect.

CorelDRAW is the budget-studio standard in India (45%) and Latin America
(38%) — the segments most price-sensitive about software stacks. The
.cdr binary format is proprietary; the only open parser (`libcdr` from
LibreOffice) is C++ with limited Python bindings and only partial
coverage of recent CorelDRAW releases.

This importer takes the same pragmatic v1 path as `dwg_importer`:

  1. Detect CorelDRAW signature via the RIFF/RIFX wrapper.
  2. Extract CDR version from the form chunk type ("CDR9", "CDRD", ...).
  3. Emit an actionable warning telling the architect how to re-export
     to a format we can fully parse (PDF / SVG / PNG).

The version chunk tags are stable across CorelDRAW releases:

    CDR4 = CDR  4    CDRC = X5  (15)
    CDR5 = CDR  5    CDRD = X6  (16)
    CDR6 = CDR  6    CDRE = X7  (17)
    CDR7 = CDR  7    CDRF = X8  (18)
    CDR8 = CDR  8    CDR0 = 2019 / 2020
    CDR9 = CDR  9    CDRT = 2022+
    CDRA = X3 (13)
    CDRB = X4 (14)
"""

from __future__ import annotations

import struct
from typing import Any

_VERSION_MAP: dict[str, str] = {
    "CDR4": "CorelDRAW 4",
    "CDR5": "CorelDRAW 5",
    "CDR6": "CorelDRAW 6",
    "CDR7": "CorelDRAW 7",
    "CDR8": "CorelDRAW 8",
    "CDR9": "CorelDRAW 9",
    "CDRA": "CorelDRAW X3 (v13)",
    "CDRB": "CorelDRAW X4 (v14)",
    "CDRC": "CorelDRAW X5 (v15)",
    "CDRD": "CorelDRAW X6 (v16)",
    "CDRE": "CorelDRAW X7 (v17)",
    "CDRF": "CorelDRAW X8 (v18)",
    "CDR0": "CorelDRAW 2019/2020",
    "CDRT": "CorelDRAW 2022+",
}


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    if len(payload) < 12:
        return {
            "format": "cdr",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "File too short to be a valid CDR.",
            "extracted": {},
            "warnings": ["CDR header missing — file may be truncated."],
        }

    magic = payload[0:4]
    if magic not in (b"RIFF", b"RIFX"):
        return {
            "format": "cdr",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Not a valid CDR file (missing RIFF wrapper).",
            "extracted": {},
            "warnings": ["CDR files start with RIFF/RIFX; this file does not."],
        }

    try:
        # RIFF is little-endian; RIFX big-endian. The riff_size is bytes-following.
        riff_size = struct.unpack("<I" if magic == b"RIFF" else ">I", payload[4:8])[0]
    except struct.error:
        riff_size = None
    form_type = payload[8:12].decode("ascii", errors="replace")
    release = _VERSION_MAP.get(form_type, "unknown")

    if not form_type.startswith("CDR"):
        return {
            "format": "cdr",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": f"RIFF file but not CorelDRAW (form='{form_type}').",
            "extracted": {"form_type": form_type, "riff_size": riff_size},
            "warnings": [f"Expected RIFF form 'CDR?' — found '{form_type}'."],
        }

    redirect = (
        "CorelDRAW .cdr is proprietary; KATHA cannot extract geometry "
        "directly. In CorelDRAW use File → Export and save as PDF, SVG, "
        "or PNG, then re-upload. PDF preserves layout + text; SVG preserves "
        "vector paths."
    )

    return {
        "format": "cdr",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"{release} (form={form_type}); proprietary binary — re-export as "
            "PDF / SVG / PNG to extract content."
        ),
        "extracted": {
            "form_type": form_type,
            "release": release,
            "riff_size": riff_size,
            "byte_order": "little-endian" if magic == b"RIFF" else "big-endian",
            "parseable": False,
        },
        "warnings": [redirect],
    }
