"""DWG importer — ODA → DXF passthrough, with header-redirect fallback.

DWG is AutoCAD's proprietary binary format (universal — 85-90% of every
regional market). Autodesk does not publish a spec; reverse-engineered
parsers (libredwg, Teigha-derived) exist but are incomplete and add a
heavy system-level dependency.

This importer takes one of two paths:

  1. **ODA File Converter present.** The Open Design Alliance ships a
     free binary that converts DWG → DXF reliably across releases R12
     through 2024. We shell out via `app.services.oda_converter`, read
     the resulting DXF back, and route it through the existing
     `dxf_importer`. The architect's .dwg uploads behave identically
     to .dxf uploads.

  2. **ODA absent.** We fall back to detecting the DWG version from
     the 6-byte header and emitting an actionable redirect ("Save As →
     DXF or Export → IFC"). This is the v1 behaviour that shipped in
     03a6e46; it keeps local-dev and CI environments working without
     the binary.

Adding ODA at deploy time is purely a Dockerfile concern — no code
change required. Set the ``ODA_FILE_CONVERTER`` env var to point at
the binary explicitly if it lives outside the standard search paths.

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

import logging
from typing import Any

from app.services import oda_converter

logger = logging.getLogger(__name__)

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


def _release_label(code: str | None) -> str:
    if code is None:
        return "unknown"
    return _VERSION_MAP.get(code) or "unknown"


def _redirect_response(filename: str, payload: bytes, code: str, release: str) -> dict[str, Any]:
    redirect = (
        "DWG is AutoCAD's proprietary binary format. The server does not "
        "have the ODA File Converter installed, so KATHA cannot extract "
        "geometry from .dwg directly. Open in AutoCAD and use File → "
        "Save As → AutoCAD DXF (any release R2010 or newer), or "
        "File → Export → IFC, and re-upload."
    )
    return {
        "format": "dwg",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"DWG {release} ({code}); proprietary binary — re-export as DXF or "
            "IFC to extract geometry."
        ),
        "extracted": {
            "version_code": code,
            "release": release,
            "parseable": False,
            "converter": "none",
        },
        "warnings": [redirect],
    }


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

    release = _release_label(code)

    # Path 1 — ODA File Converter available: convert + route through dxf.
    if oda_converter.is_available():
        try:
            dxf_bytes = oda_converter.convert_dwg_to_dxf(payload)
        except Exception:  # noqa: BLE001
            logger.exception("ODA conversion crashed for %s", filename)
            dxf_bytes = None
        if dxf_bytes:
            # Local import — dxf_importer is at the same level, but we
            # avoid cyclic import risk by deferring it.
            from app.services.importers import dxf_importer

            dxf_result = dxf_importer.parse(
                filename.rsplit(".", 1)[0] + ".dxf",
                dxf_bytes,
            )
            # Preserve the user's original file name + size in the
            # outgoing payload, but pull in the parsed geometry the
            # DXF importer extracted. Carry a "converter" breadcrumb
            # so consumers can tell ODA-routed parses apart from
            # native-DXF uploads.
            extracted = dict(dxf_result.get("extracted") or {})
            extracted.update({
                "version_code": code,
                "release": release,
                "parseable": True,
                "converter": "oda",
                "source_format": "dwg",
            })
            warnings = list(dxf_result.get("warnings") or [])
            return {
                "format": "dwg",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": (
                    f"DWG {release} ({code}) → DXF via ODA: "
                    + (dxf_result.get("summary") or "parsed.")
                ),
                "extracted": extracted,
                "warnings": warnings,
            }
        # Conversion failed even though the binary exists — fall
        # through to the redirect with a more diagnostic warning.
        return {
            "format": "dwg",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": (
                f"DWG {release} ({code}); ODA conversion failed — "
                "file may be corrupt or from an unsupported release."
            ),
            "extracted": {
                "version_code": code,
                "release": release,
                "parseable": False,
                "converter": "oda_failed",
            },
            "warnings": [
                "ODA File Converter is installed but failed to produce a "
                "DXF from this file. Try opening in AutoCAD and exporting "
                "DXF or IFC manually."
            ],
        }

    # Path 2 — ODA absent: emit the original redirect.
    return _redirect_response(filename, payload, code, release)
