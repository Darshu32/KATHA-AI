"""IFC importer — read BIM models from Revit, ArchiCAD, Vectorworks, Tekla, etc.

IFC (Industry Foundation Classes) is the open BIM exchange standard.
Architects working in Revit, ArchiCAD, Vectorworks, and most other BIM
authoring tools can export to IFC — so this single importer is the
practical bridge for the "Import from any software" promise across the
EU-critical ArchiCAD and globally-important Revit ecosystems.

We do NOT map full geometry into the design graph (IFC files routinely
exceed 100 MB and carry thousands of typed elements). Instead this
parser extracts a reference-asset summary:

  - Schema (IFC2x3 / IFC4 / IFC4x3) and project identity
  - Site / Building / Storey hierarchy counts
  - Per-space (room) names + areas where present
  - Element-type counts (walls, doors, windows, furniture, MEP, ...)
  - Material catalogue
  - Scene bounding box

The original .ifc/.ifczip payload is preserved for downstream tools;
the design graph is enriched from this summary by the import_advisor
LLM stage.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

try:
    import ifcopenshell
except Exception:  # noqa: BLE001
    ifcopenshell = None

logger = logging.getLogger(__name__)

# Element types we count in the summary. Order matters for stable output.
_INTERESTING_TYPES: tuple[str, ...] = (
    "IfcSpace",
    "IfcWall",
    "IfcSlab",
    "IfcRoof",
    "IfcStair",
    "IfcRamp",
    "IfcDoor",
    "IfcWindow",
    "IfcColumn",
    "IfcBeam",
    "IfcCurtainWall",
    "IfcRailing",
    "IfcFurniture",
    "IfcFurnishingElement",
    "IfcSanitaryTerminal",
    "IfcElectricAppliance",
    "IfcLightFixture",
    "IfcFlowTerminal",
    "IfcFlowSegment",
    "IfcDistributionElement",
)

# Cap point iteration on very large models to keep parse time bounded.
_BBOX_POINT_CAP = 200_000


def _safe(obj, attr, default=None):
    try:
        v = getattr(obj, attr, default)
        return v if v is not None else default
    except Exception:  # noqa: BLE001
        return default


def _bbox(model) -> dict[str, Any] | None:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    count = 0
    for p in model.by_type("IfcCartesianPoint"):
        coords = list(_safe(p, "Coordinates") or [])
        if len(coords) >= 2:
            try:
                xs.append(float(coords[0]))
                ys.append(float(coords[1]))
                if len(coords) >= 3:
                    zs.append(float(coords[2]))
            except (TypeError, ValueError):
                continue
        count += 1
        if count >= _BBOX_POINT_CAP:
            break
    if not xs:
        return None
    out: dict[str, Any] = {
        "x": [min(xs), max(xs)],
        "y": [min(ys), max(ys)],
        "extent_m": [
            round(max(xs) - min(xs), 3),
            round(max(ys) - min(ys), 3),
        ],
    }
    if zs:
        out["z"] = [min(zs), max(zs)]
        out["extent_m"].append(round(max(zs) - min(zs), 3))
    return out


def _space_summary(space) -> dict[str, Any]:
    name = _safe(space, "Name") or _safe(space, "LongName") or "Space"
    area: float | None = None
    try:
        for rel in _safe(space, "IsDefinedBy") or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pset = _safe(rel, "RelatingPropertyDefinition")
            if pset is None or not pset.is_a("IfcElementQuantity"):
                continue
            for q in _safe(pset, "Quantities") or []:
                if q.is_a("IfcQuantityArea"):
                    qname = (_safe(q, "Name") or "").lower()
                    if "area" in qname or qname in {"netfloorarea", "grossfloorarea"}:
                        try:
                            area = float(_safe(q, "AreaValue") or 0.0)
                            break
                        except (TypeError, ValueError):
                            continue
            if area is not None:
                break
    except Exception:  # noqa: BLE001
        pass
    return {
        "name": str(name),
        "long_name": str(_safe(space, "LongName") or "") or None,
        "area_m2": round(area, 2) if area is not None else None,
    }


def _materials(model) -> list[str]:
    names: set[str] = set()
    for m in model.by_type("IfcMaterial"):
        n = _safe(m, "Name")
        if n:
            names.add(str(n))
    return sorted(names)


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    if ifcopenshell is None:
        return {
            "format": "ifc",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "ifcopenshell is not installed in this environment.",
            "extracted": {},
            "warnings": ["ifcopenshell import failed — install ifcopenshell to parse IFC files."],
        }

    suffix = ".ifczip" if filename.lower().endswith(".ifczip") else ".ifc"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            model = ifcopenshell.open(tmp_path)
        except Exception as exc:  # noqa: BLE001
            return {
                "format": "ifc",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": "Could not parse IFC file.",
                "extracted": {},
                "warnings": [f"ifcopenshell parse failed: {exc}"],
            }

        schema = _safe(model, "schema") or "unknown"
        projects = model.by_type("IfcProject")
        project_name: str | None = None
        if projects:
            project_name = (
                _safe(projects[0], "Name") or _safe(projects[0], "LongName") or None
            )

        sites = model.by_type("IfcSite")
        buildings = model.by_type("IfcBuilding")
        storeys = model.by_type("IfcBuildingStorey")
        spaces = [_space_summary(s) for s in model.by_type("IfcSpace")]

        type_counts: dict[str, int] = {}
        for t in _INTERESTING_TYPES:
            try:
                n = len(model.by_type(t))
            except Exception:  # noqa: BLE001
                continue
            if n > 0:
                type_counts[t] = n

        materials = _materials(model)
        bbox = _bbox(model)

        extracted: dict[str, Any] = {
            "schema": str(schema),
            "project_name": str(project_name) if project_name else None,
            "site_count": len(sites),
            "building_count": len(buildings),
            "storey_count": len(storeys),
            "space_count": len(spaces),
            "spaces": spaces[:50],
            "element_counts": type_counts,
            "element_total": sum(type_counts.values()),
            "material_count": len(materials),
            "materials": materials[:50],
            "bbox": bbox,
        }

        extent_str = ""
        if bbox and bbox.get("extent_m"):
            ext = bbox["extent_m"]
            if len(ext) >= 3:
                extent_str = f"; extent {ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} m"
            elif len(ext) == 2:
                extent_str = f"; extent {ext[0]:.1f} × {ext[1]:.1f} m"

        summary = (
            f"IFC {schema}: {len(storeys)} storey(s), {len(spaces)} space(s), "
            f"{extracted['element_total']} typed element(s){extent_str}."
        )

        return {
            "format": "ifc",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": summary,
            "extracted": extracted,
            "warnings": [],
        }
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
