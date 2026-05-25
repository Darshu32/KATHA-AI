"""File-format importers (BRD Layer 5B).

Each importer parses an uploaded file into a normalised payload the
LLM ingestion stage can reason about. Importers are deterministic and
never call the network — they extract text, dimensions, geometry, or
tabular rows; the *meaning* is left to the import_advisor service.

Common return shape:

    {
        "format": "<pdf|image|dxf|step|obj|csv|xlsx|docx|text>",
        "filename": str,
        "size_bytes": int,
        "summary": str,                   # one-line human description
        "extracted": {...},               # format-specific fields
        "warnings": [str, ...],
    }
"""

from __future__ import annotations

from app.services.importers import (
    cdr_importer,
    csv_importer,
    docx_importer,
    dwg_importer,
    dxf_importer,
    ifc_importer,
    image_importer,
    obj_importer,
    pdf_importer,
    psd_importer,
    rhino_importer,
    skp_importer,
    step_importer,
    text_importer,
    xlsx_importer,
)

_REGISTRY = {
    "pdf":  pdf_importer,
    "png":  image_importer,
    "jpg":  image_importer,
    "jpeg": image_importer,
    "psd":  psd_importer,         # Photoshop (universal — 80-90% adoption)
    "psb":  psd_importer,         # Photoshop large-document format
    "dxf":  dxf_importer,
    "dwg":  dwg_importer,         # version detect + redirect to DXF/IFC
    "ifc":  ifc_importer,         # BIM — Revit/ArchiCAD/Vectorworks export here
    "ifczip": ifc_importer,       # zip-compressed IFC
    "3dm":  rhino_importer,       # Rhino / Grasshopper (parametric)
    "skp":  skp_importer,         # SketchUp — version detect + redirect to OBJ
    "cdr":  cdr_importer,         # CorelDRAW — India/LatAm budget segments
    "step": step_importer,
    "stp":  step_importer,
    "iges": step_importer,
    "obj":  obj_importer,
    "fbx":  obj_importer,         # graceful: warns + extracts what it can
    "gltf": obj_importer,
    "csv":  csv_importer,
    "xlsx": xlsx_importer,
    "xls":  xlsx_importer,
    "docx": docx_importer,
    "txt":  text_importer,
    "md":   text_importer,
}


def detect(filename: str) -> str | None:
    if "." not in filename:
        return None
    return filename.rsplit(".", 1)[1].lower()


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY.keys())


def parse(filename: str, payload: bytes) -> dict:
    ext = detect(filename) or ""
    module = _REGISTRY.get(ext)
    if module is None:
        return {
            "format": ext or "unknown",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": f"Unsupported file extension '.{ext}'.",
            "extracted": {},
            "warnings": [f"No importer registered for '.{ext}'."],
        }
    return module.parse(filename, payload)


__all__ = ["detect", "parse", "supported_extensions"]
