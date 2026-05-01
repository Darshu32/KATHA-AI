# ADR 0005 — IFC export instead of native Revit (.rvt)

Status: Accepted
Date: 2026-05-01
Stage: 10 (BRD Phase 1 closure)

## Context

BRD §5A asks for an export the architect can use in Autodesk
Revit. The literal interpretation is "produce a `.rvt` file."
That interpretation runs into hard reality:

| Approach to .rvt | Verdict |
|---|---|
| Revit Desktop API (Python via pyRevit) | Requires Revit Desktop running on Windows. Not viable in a Linux backend service. |
| ODA Drawings SDK | Commercial, paid licensing (~$$$ per seat / per server). |
| Reverse-engineered .rvt writer | None exist that survive Autodesk's file-format updates. |

Meanwhile, **IFC (Industry Foundation Classes)** is the BIM
industry's interoperability standard. Revit ships with a built-in
IFC importer; ArchiCAD, Vectorworks, Tekla, Navisworks, Solibri,
BIMVision all open IFC natively. ifcopenshell is a free, mature,
open-source library for writing IFC4 files.

## Decision

Ship **IFC4 export** via `ifcopenshell` as the path to "architect
uses the design in Revit." Document the workflow:

1. Architect calls `export_design_bundle(format="ifc")`.
2. The IFC4 exporter emits a single `.ifc` file with `IfcProject →
   IfcSite → IfcBuilding → IfcBuildingStorey` containing rooms
   (`IfcSpace`) and objects (`IfcFurniture`, `IfcDoor`, …).
3. Architect imports into Revit via *Insert → Link IFC* or
   *Open IFC*. One click.

The BRD asked for an outcome ("the architect can use the design
in Revit"). We deliver the outcome. The file extension differs;
the workflow is faster, multi-vendor, and zero-licensing-cost.

## Alternatives considered

- **Native .rvt via Windows worker + pyRevit** — rejected for
  Phase 1. Adds a Windows host to the deployment footprint, a
  Revit Desktop license per worker, and per-version compatibility
  testing. Triggers Phase-2 status.
- **ODA Drawings SDK** — rejected for Phase 1. Commercial cost +
  licensing complexity; not justified until a customer specifically
  requires native .rvt.
- **DWG-only** — rejected. DWG is 2D / 2.5D; IFC carries the full
  3D + metadata + space tree. Architects asking for "Revit"
  generally mean the 3D model, not 2D plans.

## Consequences

- **Documented as ⚠️ Via Interop** in `docs/brd-compliance.md` —
  honest about the file extension difference; clear about the
  workflow.
- **15 export formats already ship** (Stage 4H + supporting
  exporters): PDF, DOCX, XLSX, PPTX, HTML, DXF, OBJ, GLTF, FBX,
  IFC, STEP, IGES, gcode, cam_prep, GeoJSON. IFC isn't the only
  CAD path; STEP covers parametric solid CAD.
- **Phase 2 trigger** — sign a customer who specifically requires
  a native `.rvt` deliverable. Then add a Windows worker that
  consumes the IFC and emits .rvt via Revit's API. The framework
  doesn't change; one new exporter module appears.
- **Vendor partnerships** — same logic for Jaquar / Kohler /
  AutoCAD-specific outputs. Phase 1 ships standards; phase 2
  ships per-partner adapters.

Re-evaluate at: a customer contract that explicitly requires
`.rvt` (not "Revit-compatible IFC"). Until then, IFC is the
right answer.
