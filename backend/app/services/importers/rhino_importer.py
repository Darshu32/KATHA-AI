"""Rhino .3dm importer — parametric/NURBS models from Rhinoceros via rhino3dm.

Rhino is the parametric-design hub for architects (25-30% adoption in
North America, Asia-Pacific; the home of Grasshopper). rhino3dm is
McNeel's official MIT-licensed Python binding to the openNURBS kernel
that Rhino itself uses, so this importer reads .3dm files with the same
fidelity Rhino does — no reverse-engineering, no proprietary SDK.

We do NOT load full NURBS surface data into the design graph (a single
Rhino model can carry millions of control points). Instead the importer
extracts a reference-asset summary:

  - File version (Rhino 4 / 5 / 6 / 7 / 8 ...)
  - Model unit system + tolerances
  - Layer tree (visible names + hierarchy)
  - Per-object-type counts (curves, meshes, breps, extrusions, ...)
  - Material catalogue
  - World bounding box across all objects

The original .3dm payload is preserved so downstream tools can render
it; the design graph is enriched from this summary by the import_advisor
LLM stage.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

try:
    import rhino3dm
except Exception:  # noqa: BLE001
    rhino3dm = None

logger = logging.getLogger(__name__)


def _unit_name(system_id: int | None) -> str:
    # rhino3dm.UnitSystem enum — mirror values from openNURBS.
    return {
        0: "none",
        1: "microns",
        2: "millimeters",
        3: "centimeters",
        4: "meters",
        5: "kilometers",
        6: "microinches",
        7: "mils",
        8: "inches",
        9: "feet",
        10: "miles",
        11: "custom",
        12: "angstroms",
        13: "nanometers",
        14: "decimeters",
        15: "dekameters",
        16: "hectometers",
        17: "megameters",
        18: "gigameters",
        19: "yards",
        20: "printer-points",
        21: "printer-picas",
        22: "nautical-miles",
        23: "astronomical-units",
        24: "light-years",
        25: "parsecs",
    }.get(int(system_id) if system_id is not None else -1, "unknown")


def _safe(obj, attr, default=None):
    try:
        v = getattr(obj, attr, default)
        return v if v is not None else default
    except Exception:  # noqa: BLE001
        return default


def _geometry_type(geom) -> str:
    if geom is None:
        return "None"
    return type(geom).__name__


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    if rhino3dm is None:
        return {
            "format": "3dm",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "rhino3dm is not installed in this environment.",
            "extracted": {},
            "warnings": ["rhino3dm import failed — install rhino3dm to parse .3dm files."],
        }

    # rhino3dm reads from a file path. Write to a temp file.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".3dm", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            model = rhino3dm.File3dm.Read(tmp_path)
        except Exception as exc:  # noqa: BLE001
            return {
                "format": "3dm",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": "Could not parse .3dm file.",
                "extracted": {},
                "warnings": [f"rhino3dm parse failed: {exc}"],
            }
        if model is None:
            return {
                "format": "3dm",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": "Could not parse .3dm file (rhino3dm returned None).",
                "extracted": {},
                "warnings": ["File may be truncated or from an unsupported Rhino release."],
            }

        # Application version (Rhino release number, e.g. 7, 8).
        application_version = _safe(model, "ApplicationVersion")
        archive_version = _safe(model, "ArchiveVersion")
        # Some attributes are accessed through Settings on newer rhino3dm.
        settings = _safe(model, "Settings")
        model_unit = None
        model_tol = None
        if settings is not None:
            model_unit = _safe(settings, "ModelUnitSystem")
            model_tol = _safe(settings, "ModelAbsoluteTolerance")

        # Layers.
        layers = []
        try:
            for layer in model.Layers:
                layers.append({
                    "name": _safe(layer, "Name") or "",
                    "full_path": _safe(layer, "FullPath") or _safe(layer, "Name") or "",
                    "visible": bool(_safe(layer, "Visible", True)),
                })
        except Exception:  # noqa: BLE001
            pass

        # Objects — count by geometry type + accumulate bbox.
        type_counts: dict[str, int] = {}
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        object_total = 0
        try:
            for obj in model.Objects:
                object_total += 1
                geom = _safe(obj, "Geometry")
                gtype = _geometry_type(geom)
                type_counts[gtype] = type_counts.get(gtype, 0) + 1
                # Try to get bounding box for this object.
                bbox = None
                try:
                    bbox = geom.GetBoundingBox()
                except Exception:  # noqa: BLE001
                    bbox = None
                if bbox is None:
                    continue
                try:
                    mn = bbox.Min
                    mx = bbox.Max
                    xs.extend([float(mn.X), float(mx.X)])
                    ys.extend([float(mn.Y), float(mx.Y)])
                    zs.extend([float(mn.Z), float(mx.Z)])
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass

        # Materials.
        materials: list[str] = []
        try:
            for mat in model.Materials:
                name = _safe(mat, "Name") or ""
                if name:
                    materials.append(str(name))
        except Exception:  # noqa: BLE001
            pass
        # Dedupe + bound list size.
        materials = sorted(set(materials))[:50]

        bbox: dict[str, Any] | None = None
        if xs:
            bbox = {
                "x": [min(xs), max(xs)],
                "y": [min(ys), max(ys)],
                "z": [min(zs), max(zs)],
                "extent": [
                    round(max(xs) - min(xs), 3),
                    round(max(ys) - min(ys), 3),
                    round(max(zs) - min(zs), 3),
                ],
            }

        unit_name = _unit_name(model_unit)
        extent_str = ""
        if bbox and bbox.get("extent"):
            e = bbox["extent"]
            extent_str = f"; extent {e[0]:.2f} × {e[1]:.2f} × {e[2]:.2f} {unit_name}"

        version_bits: list[str] = []
        if archive_version is not None:
            version_bits.append(f"archive v{archive_version}")
        if application_version:
            version_bits.append(f"app v{application_version}")
        version_str = (" (" + ", ".join(version_bits) + ")") if version_bits else ""
        summary = (
            f"Rhino .3dm{version_str}: "
            f"{len(layers)} layer(s), {object_total} object(s), "
            f"{len(materials)} material(s){extent_str}."
        )

        return {
            "format": "3dm",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": summary,
            "extracted": {
                "application_version": application_version,
                "archive_version": archive_version,
                "model_unit_system": unit_name,
                "model_absolute_tolerance": model_tol,
                "layer_count": len(layers),
                "layers": layers[:50],
                "object_total": object_total,
                "geometry_type_counts": type_counts,
                "material_count": len(materials),
                "materials": materials,
                "bbox": bbox,
            },
            "warnings": [],
        }
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
