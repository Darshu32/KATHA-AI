"""File-format exporters (BRD Layer 5A — Pass A).

Each exporter consumes a `spec_bundle` from `services.specs.build_spec_bundle`
and returns raw bytes + metadata.
"""

from __future__ import annotations

from app.services.exporters import (
    cam_prep_exporter,
    docx_exporter,
    dxf_exporter,
    fbx_exporter,
    gcode_exporter,
    geojson_exporter,
    gltf_exporter,
    html_exporter,
    ifc_exporter,
    iges_exporter,
    obj_exporter,
    pdf_exporter,
    pptx_exporter,
    step_exporter,
    xlsx_exporter,
)

_REGISTRY = {
    # Pass A — documents
    "pdf": pdf_exporter,
    "docx": docx_exporter,
    "xlsx": xlsx_exporter,
    "pptx": pptx_exporter,           # client-facing slide deck
    "html": html_exporter,           # interactive single-file viewer
    # Pass B — CAD / 3D
    "dxf": dxf_exporter,             # AutoCAD-compatible 2D plans
    "obj": obj_exporter,             # SketchUp / Rhino / Blender mesh
    "gltf": gltf_exporter,           # web-friendly 3D
    "fbx": fbx_exporter,             # 3DS Max / Maya / Unreal / Unity
    # Pass C — BIM / CAD exchange / specialist
    "ifc": ifc_exporter,             # BIM (IFC4 — Revit/ArchiCAD/Vectorworks ingest)
    "step": step_exporter,           # parametric solid CAD exchange (CATIA/NX/SW)
    "iges": iges_exporter,           # legacy CAD exchange (older CATIA/Pro-E)
    "gcode": gcode_exporter,         # CNC routing program — nested, multi-tool
    "cam_prep": cam_prep_exporter,   # CAM prep bundle — nest SVG + JSON + QA + assembly
    "geojson": geojson_exporter,     # structured plan + metadata for BIM/GIS/PM
}


def available_formats() -> list[str]:
    return list(_REGISTRY.keys())


def export(format_key: str, spec_bundle: dict, graph: dict | None = None) -> dict:
    """Return {content_type, filename, bytes}."""
    format_key = format_key.lower()
    module = _REGISTRY.get(format_key)
    if not module:
        raise ValueError(f"Unsupported export format '{format_key}'. Available: {list(_REGISTRY)}")
    return module.export(spec_bundle, graph or {})


__all__ = ["available_formats", "export"]
