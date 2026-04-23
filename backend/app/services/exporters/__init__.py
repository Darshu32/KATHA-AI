"""File-format exporters (BRD Layer 5A — Pass A).

Each exporter consumes a `spec_bundle` from `services.specs.build_spec_bundle`
and returns raw bytes + metadata.
"""

from __future__ import annotations

from app.services.exporters import (
    docx_exporter,
    dxf_exporter,
    gcode_exporter,
    gltf_exporter,
    ifc_exporter,
    obj_exporter,
    pdf_exporter,
    step_exporter,
    xlsx_exporter,
)

_REGISTRY = {
    # Pass A — documents
    "pdf": pdf_exporter,
    "docx": docx_exporter,
    "xlsx": xlsx_exporter,
    # Pass B — CAD / 3D
    "dxf": dxf_exporter,
    "obj": obj_exporter,
    "gltf": gltf_exporter,
    # Pass C — BIM / specialist
    "ifc": ifc_exporter,
    "step": step_exporter,
    "gcode": gcode_exporter,
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
