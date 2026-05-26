"""ODA File Converter wrapper — convert DWG / DXF binary CAD files.

Autodesk does not publish the DWG binary spec. The reverse-engineered
libraries (libredwg, dwg2dxf) are incomplete; the only reliable open
path is the Open Design Alliance's ``ODAFileConverter`` — a free
download from https://www.opendesign.com/guestfiles/oda_file_converter
that we install at backend deploy time.

This module is small and intentionally narrow: a single detection
function + a single conversion function. The DWG importer calls in
when present and falls back to its existing redirect-to-DXF behaviour
when ``is_available()`` returns False, so local dev / CI environments
without ODA still build and run.

The ODA CLI signature is fixed across versions:

    ODAFileConverter <input_folder> <output_folder>
                     <output_version> <output_format>
                     <recurse> <audit> [<filter>]

We always use ACAD2018 + DXF + no recurse + audit-on.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# Candidate paths in priority order. Linux-x86_64 deploy puts the binary
# on PATH; macOS dev installs the app bundle.
_CANDIDATES: tuple[str, ...] = (
    "ODAFileConverter",  # PATH (Linux production image)
    "/usr/bin/ODAFileConverter",
    "/usr/local/bin/ODAFileConverter",
    "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
    "/opt/oda/ODAFileConverter",
)

_DEFAULT_TIMEOUT_S = 60
_OUTPUT_VERSION = "ACAD2018"
_OUTPUT_FORMAT = "DXF"


def _locate_binary() -> str | None:
    """Return the resolved path to the ODAFileConverter binary, or None."""
    override = os.environ.get("ODA_FILE_CONVERTER")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    for candidate in _CANDIDATES:
        if "/" in candidate:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None


def is_available() -> bool:
    """Cheap probe — does ODAFileConverter exist and look runnable?"""
    return _locate_binary() is not None


def convert_dwg_to_dxf(payload: bytes, timeout_s: int = _DEFAULT_TIMEOUT_S) -> bytes | None:
    """Convert a DWG byte payload to DXF bytes via the ODA CLI.

    Returns the converted DXF bytes on success, or None on any failure
    (binary missing, conversion error, or no output file produced).
    The caller is expected to treat None as "fall back" — never raise.

    Subprocess never sees user-controlled paths or arg strings; only
    the bytes we wrote into our own tempdir. shell=False (the default).
    """
    binary = _locate_binary()
    if binary is None:
        return None

    with tempfile.TemporaryDirectory(prefix="oda_in_") as in_dir, \
         tempfile.TemporaryDirectory(prefix="oda_out_") as out_dir:
        in_path = Path(in_dir) / "input.dwg"
        in_path.write_bytes(payload)

        try:
            proc = subprocess.run(
                [
                    binary,
                    in_dir,
                    out_dir,
                    _OUTPUT_VERSION,
                    _OUTPUT_FORMAT,
                    "0",      # recurse
                    "1",      # audit
                    "*.dwg",  # filter
                ],
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("ODAFileConverter timed out after %ss", timeout_s)
            return None
        except (OSError, FileNotFoundError) as exc:
            logger.warning("ODAFileConverter spawn failed: %s", exc)
            return None

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:400] if proc.stderr else ""
            logger.warning(
                "ODAFileConverter returned %d: %s", proc.returncode, stderr
            )
            # ODA sometimes returns non-zero even when conversion
            # succeeded (audit warnings) — fall through to output check.

        # Output filename mirrors the input stem with the new extension.
        out_path = Path(out_dir) / "input.dxf"
        if not out_path.is_file():
            return None
        try:
            return out_path.read_bytes()
        except OSError:
            return None
