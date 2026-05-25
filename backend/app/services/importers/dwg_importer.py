"""DWG importer — version detection + actionable redirect to DXF/IFC.

DWG is AutoCAD's proprietary binary format (universal — 85-90% of every
regional market). Autodesk does not publish a spec; reverse-engineered
parsers (libredwg, Teigha-derived) exist but are incomplete and add a
heavy system-level dependency.

This importer takes the pragmatic v1 path:

  1. Detect the DWG version from the 6-byte header signature.
  2. Report version, file size, and structural pointers.
  3. Emit an actionable warning telling the architect how to re-export
     to a format we can fully parse (DXF or IFC).

A v2 will shell out to the ODA File Converter (free Open Design
Alliance binary) to produce a DXF on the server side and route through
the existing dxf_importer. That requires packaging the converter into
the backend image; deferred for now.

The version code is well-documented in Autodesk's release notes:

    AC1006  R10        AC1027  R2013
    AC1009  R11/R12    AC1032  R2018
    AC1012  R13        AC1035  R2024
    AC1014  R14
    AC1015  R2000
    AC1018  R2004
    AC1021  R2007
    AC1024  R2010
"""

from __future__ import annotations

from typing import Any

_VERSION_MAP: dict[str, str] = {
    "AC1006": "R10",
    "AC1009": "R11/R12",
    "AC1012": "R13",
    "AC1014": "R14",
    "AC1015": "R2000",
    "AC1018": "R2004",
    "AC1021": "R2007",
    "AC1024": "R2010",
    "AC1027": "R2013",
    "AC1032": "R2018",
    "AC1035": "R2024",
}


def _version_code(payload: bytes) -> str | None:
    if len(payload) < 6:
        return None
    code = payload[:6].decode("ascii", errors="replace")
    if not code.startswith("AC"):
        return None
    return code


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    code = _version_code(payload)
    if code is None:
        return {
            "format": "dwg",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Not a valid DWG file (bad header).",
            "extracted": {},
            "warnings": ["DWG header signature missing — file may be truncated or not a DWG."],
        }

    release = _VERSION_MAP.get(code) or "unknown"
    redirect = (
        "DWG is AutoCAD's proprietary binary format. KATHA cannot parse "
        "geometry from .dwg directly. Open in AutoCAD and use File → Save As → "
        "AutoCAD DXF (any release R2010 or newer), or File → Export → IFC, "
        "and re-upload."
    )

    return {
        "format": "dwg",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"DWG {release} ({code}); proprietary binary — re-export as DXF or IFC to "
            "extract geometry."
        ),
        "extracted": {
            "version_code": code,
            "release": release,
            "parseable": False,
        },
        "warnings": [redirect],
    }
