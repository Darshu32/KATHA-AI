"""SketchUp .skp importer — header detect + actionable redirect to OBJ/COLLADA.

SketchUp is universal in SME architecture (70-80% adoption in every
regional market). The .skp file format is proprietary and the official
SketchUp SDK is C++ only — no usable Python bindings exist for routine
deployment. Trimble does not publish the binary spec.

This importer takes the same pragmatic v1 path as `dwg_importer` and
`cdr_importer`:

  1. Detect the SketchUp magic in the file header (UTF-16LE string
     containing "SketchUp Model" near the start of the file).
  2. Extract the embedded version string when present (e.g. "Ver8.0",
     "Ver15.0", "Ver24.0" for 2024 release).
  3. Emit an actionable warning explaining the export path — SketchUp's
     File → Export → 3D Model → OBJ is one click, and we already parse
     OBJ via the obj_importer. (COLLADA .dae support TBD; for now we
     point users at OBJ which is universally produced by SketchUp.)

A v2 may shell out to SketchUp's free Make-era command-line tools (no
longer maintained) or use a Trimble Cloud round-trip; both are
fragile. The redirect is the honest answer for v1.
"""

from __future__ import annotations

import re
from typing import Any

# Matches a UTF-16LE-encoded "SketchUp Model" within the leading header
# region. Each ASCII char appears as `<char>\x00` little-endian.
_SKETCHUP_MAGIC_UTF16 = (
    b"S\x00k\x00e\x00t\x00c\x00h\x00U\x00p\x00 \x00M\x00o\x00d\x00e\x00l\x00"
)
# Some older files leak the ASCII form as well.
_SKETCHUP_MAGIC_ASCII = b"SketchUp Model"

# Version-string pattern (UTF-16LE-encoded "Ver" + version number).
_VERSION_PATTERN_UTF16 = re.compile(
    rb"V\x00e\x00r\x00((?:[0-9]\x00){1,2}(?:\.\x00(?:[0-9]\x00){1,2})?)"
)
_VERSION_PATTERN_ASCII = re.compile(rb"Ver(\d{1,2}(?:\.\d{1,2})?)")

# Year mapping for SketchUp internal Ver numbers (publicly documented).
_VERSION_YEAR_MAP: dict[str, str] = {
    "6": "SketchUp 6 (2007)",
    "7": "SketchUp 7 (2008)",
    "8": "SketchUp 8 (2010)",
    "13": "SketchUp 2013",
    "14": "SketchUp 2014",
    "15": "SketchUp 2015",
    "16": "SketchUp 2016",
    "17": "SketchUp 2017",
    "18": "SketchUp 2018",
    "19": "SketchUp 2019",
    "20": "SketchUp 2020",
    "21": "SketchUp 2021",
    "22": "SketchUp 2022",
    "23": "SketchUp 2023",
    "24": "SketchUp 2024",
    "25": "SketchUp 2025",
}


def _extract_version(head: bytes) -> str | None:
    m = _VERSION_PATTERN_UTF16.search(head)
    if m:
        raw = m.group(1).replace(b"\x00", b"").decode("ascii", errors="ignore")
        return raw or None
    m2 = _VERSION_PATTERN_ASCII.search(head)
    if m2:
        return m2.group(1).decode("ascii", errors="ignore")
    return None


def _release_label(version: str | None) -> str:
    if not version:
        return "unknown release"
    major = version.split(".")[0]
    return _VERSION_YEAR_MAP.get(major, f"SketchUp (Ver{version})")


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    # Only inspect the first 4 KB — magic + version live near the start.
    head = payload[: 4096]

    has_utf16 = _SKETCHUP_MAGIC_UTF16 in head
    has_ascii = _SKETCHUP_MAGIC_ASCII in head
    if not (has_utf16 or has_ascii):
        return {
            "format": "skp",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Not a recognised SketchUp file (magic missing).",
            "extracted": {},
            "warnings": [
                "SketchUp 'Model' magic not found in the first 4 KB — file "
                "may be truncated or from an unsupported release."
            ],
        }

    version = _extract_version(head)
    release = _release_label(version)

    redirect = (
        "SketchUp .skp is proprietary and KATHA cannot extract geometry "
        "directly. In SketchUp use File → Export → 3D Model → Wavefront "
        "(.obj) — KATHA imports OBJ. For 2D plans, File → Export → 2D "
        "Graphic → PDF also works."
    )

    return {
        "format": "skp",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"{release}"
            + (f" (Ver{version})" if version else "")
            + "; proprietary binary — re-export as OBJ to extract geometry."
        ),
        "extracted": {
            "version": version,
            "release": release,
            "magic_encoding": "utf-16le" if has_utf16 else "ascii",
            "parseable": False,
        },
        "warnings": [redirect],
    }
