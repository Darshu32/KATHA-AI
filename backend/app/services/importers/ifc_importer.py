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
    import ifcopenshell.util.element as _ifc_element
    import ifcopenshell.util.unit as _ifc_unit
except Exception:  # noqa: BLE001
    ifcopenshell = None
    _ifc_element = None
    _ifc_unit = None

logger = logging.getLogger(__name__)


# Canonical IFC quantity / property names we look for on IfcSpace. Keys
# are normalised (lower-cased, stripped of underscores + whitespace) so
# the lookup tolerates "NetFloorArea" / "Net Floor Area" / "net_area"
# / "NETAREA" without per-author guesswork.
#
# Order within each tuple is preference: the first match wins. Net
# values are preferred over gross because they reflect usable interior
# area — the number an architect actually thinks in.
_AREA_NET_KEYS: tuple[str, ...] = (
    "netfloorarea", "netplannedarea", "netarea",
)
_AREA_GROSS_KEYS: tuple[str, ...] = (
    "grossfloorarea", "grossplannedarea", "grossarea",
)
_AREA_GENERIC_KEYS: tuple[str, ...] = (
    "area",
)
_VOLUME_NET_KEYS: tuple[str, ...] = ("netvolume",)
_VOLUME_GROSS_KEYS: tuple[str, ...] = ("grossvolume",)
_VOLUME_GENERIC_KEYS: tuple[str, ...] = ("volume",)
_PERIMETER_NET_KEYS: tuple[str, ...] = ("netperimeter",)
_PERIMETER_GROSS_KEYS: tuple[str, ...] = ("grossperimeter",)
_PERIMETER_GENERIC_KEYS: tuple[str, ...] = ("perimeter",)
_HEIGHT_KEYS: tuple[str, ...] = (
    "height", "finishfloortofinishceilingheight", "ceilingheight",
)


def _norm_key(s: str) -> str:
    return s.replace(" ", "").replace("_", "").lower()


def _find_quantity(psets: dict[str, dict[str, Any]], candidates: tuple[str, ...]) -> float | None:
    """Walk every pset/qset property looking for the first key whose
    normalised form matches one of the candidates. Returns the value as
    a float, or None if no candidate appears."""
    candidate_set = set(candidates)
    for _pset_name, props in psets.items():
        if not isinstance(props, dict):
            continue
        for raw_key, raw_val in props.items():
            if _norm_key(str(raw_key)) not in candidate_set:
                continue
            try:
                return float(raw_val)
            except (TypeError, ValueError):
                continue
    return None

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


def _space_summary(space, length_scale: float) -> dict[str, Any]:
    """Build a quantity-rich summary for an IfcSpace.

    Uses ifcopenshell.util.element.get_psets() so we cover both
    BaseQuantities (IfcElementQuantity → IfcQuantityArea/Volume/Length)
    AND property sets like Pset_SpaceCommon (NetPlannedArea,
    GrossPlannedArea). Authors disagree on which place to put the same
    number; we look in both.

    `length_scale` is the file's length unit expressed in metres
    (computed once via ifcopenshell.util.unit.calculate_unit_scale).
    We apply scale^2 to areas and scale^3 to volumes so a model
    authored in millimetres still produces m² / m³ values.
    """
    name = _safe(space, "Name") or _safe(space, "LongName") or "Space"
    long_name = _safe(space, "LongName") or None

    psets: dict[str, dict[str, Any]] = {}
    if _ifc_element is not None:
        try:
            psets = _ifc_element.get_psets(space) or {}
        except Exception:  # noqa: BLE001
            psets = {}

    area_scale = length_scale * length_scale
    volume_scale = length_scale * length_scale * length_scale

    def _area(keys: tuple[str, ...]) -> float | None:
        v = _find_quantity(psets, keys)
        return v * area_scale if v is not None else None

    def _volume(keys: tuple[str, ...]) -> float | None:
        v = _find_quantity(psets, keys)
        return v * volume_scale if v is not None else None

    def _length(keys: tuple[str, ...]) -> float | None:
        v = _find_quantity(psets, keys)
        return v * length_scale if v is not None else None

    net_area = _area(_AREA_NET_KEYS)
    gross_area = _area(_AREA_GROSS_KEYS)
    if net_area is None and gross_area is None:
        # Last-ditch — accept any property literally named "Area".
        generic = _area(_AREA_GENERIC_KEYS)
    else:
        generic = None

    net_volume = _volume(_VOLUME_NET_KEYS)
    gross_volume = _volume(_VOLUME_GROSS_KEYS)
    if net_volume is None and gross_volume is None:
        generic_volume = _volume(_VOLUME_GENERIC_KEYS)
    else:
        generic_volume = None

    net_perimeter = _length(_PERIMETER_NET_KEYS)
    gross_perimeter = _length(_PERIMETER_GROSS_KEYS)
    if net_perimeter is None and gross_perimeter is None:
        generic_perimeter = _length(_PERIMETER_GENERIC_KEYS)
    else:
        generic_perimeter = None

    height = _length(_HEIGHT_KEYS)

    # Preferred single-value "area_m2" for backward compat — prefer net,
    # then gross, then anything-area-named.
    area_m2 = net_area if net_area is not None else gross_area if gross_area is not None else generic
    volume_m3 = (
        net_volume if net_volume is not None
        else gross_volume if gross_volume is not None
        else generic_volume
    )
    perimeter_m = (
        net_perimeter if net_perimeter is not None
        else gross_perimeter if gross_perimeter is not None
        else generic_perimeter
    )

    def _r2(v: float | None) -> float | None:
        return round(v, 2) if v is not None else None

    def _r3(v: float | None) -> float | None:
        return round(v, 3) if v is not None else None

    return {
        "name": str(name),
        "long_name": str(long_name) if long_name else None,
        "area_m2": _r2(area_m2),
        "net_floor_area_m2": _r2(net_area),
        "gross_floor_area_m2": _r2(gross_area),
        "volume_m3": _r2(volume_m3),
        "perimeter_m": _r3(perimeter_m),
        "height_m": _r3(height),
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
        # Length unit scale: 1.0 for files in metres, 0.001 for mm,
        # 0.3048 for feet, etc. Areas use scale^2, volumes scale^3.
        # Falls back to 1.0 if the helper isn't available.
        length_scale = 1.0
        if _ifc_unit is not None:
            try:
                length_scale = float(_ifc_unit.calculate_unit_scale(model) or 1.0)
            except Exception:  # noqa: BLE001
                length_scale = 1.0
        spaces = [_space_summary(s, length_scale) for s in model.by_type("IfcSpace")]

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
            "length_scale_to_m": round(length_scale, 6),
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
