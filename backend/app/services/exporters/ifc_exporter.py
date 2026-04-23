"""IFC 4 exporter — BIM-compatible building model via ifcopenshell.

Produces a single .ifc file with:
  IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey
                                      ├── IfcSpace (room)
                                      └── IfcFurnishingElement × objects
Each furnishing carries its material + bounding box dimensions. Opens
cleanly in Revit, ArchiCAD, BIMVision, Navisworks, Solibri.
"""

from __future__ import annotations

import math
import time
import uuid

import ifcopenshell
from ifcopenshell.api import run


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _guid() -> str:
    return ifcopenshell.guid.compress(uuid.uuid4().hex)


def _type_to_ifc_class(otype: str) -> str:
    """Map design object type → most appropriate IFC4 entity."""
    t = (otype or "").lower()
    if t == "door":
        return "IfcDoor"
    if t == "window":
        return "IfcWindow"
    if t in {"wall"}:
        return "IfcWall"
    if t in {"switch", "socket", "outlet", "light_fixture", "lamp", "floor_lamp"}:
        return "IfcElectricAppliance"
    if t in {"water_closet", "wc", "toilet", "wash_basin", "sink", "kitchen_sink", "bathtub", "shower"}:
        return "IfcSanitaryTerminal"
    return "IfcFurniture"


def _make_local_placement(model, x=0.0, y=0.0, z=0.0, relative_to=None):
    return model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=relative_to,
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint",
                Coordinates=[float(x), float(y), float(z)],
            ),
        ),
    )


def _box_body_rep(model, context, l, h, w):
    """IfcExtrudedAreaSolid from a rectangle profile."""
    profile = model.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        Position=model.create_entity(
            "IfcAxis2Placement2D",
            Location=model.create_entity(
                "IfcCartesianPoint", Coordinates=[0.0, 0.0]
            ),
        ),
        XDim=float(l),
        YDim=float(w),
    )
    solid = model.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint", Coordinates=[0.0, 0.0, 0.0]
            ),
        ),
        ExtrudedDirection=model.create_entity(
            "IfcDirection", DirectionRatios=[0.0, 0.0, 1.0]
        ),
        Depth=float(h),
    )
    return model.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid],
    )


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    room_dims = room.get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    room_h = float(room_dims.get("height") or 3.0)

    # Bootstrap a fresh IFC4 model via the high-level API.
    model = ifcopenshell.file(schema="IFC4")
    run("root.create_entity", model, ifc_class="IfcProject", name=project_name)
    run("unit.assign_unit", model)
    context = run("context.add_context", model, context_type="Model")
    body_context = run(
        "context.add_context",
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )

    site = run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", model, ifc_class="IfcBuilding", name=project_name)
    storey = run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")
    run("aggregate.assign_object", model, relating_object=model.by_type("IfcProject")[0], products=[site])
    run("aggregate.assign_object", model, relating_object=site, products=[building])
    run("aggregate.assign_object", model, relating_object=building, products=[storey])

    # Space (the room).
    space = run("root.create_entity", model, ifc_class="IfcSpace", name=(room.get("type") or "Room"))
    space.ObjectPlacement = _make_local_placement(model, 0, 0, 0, relative_to=storey.ObjectPlacement)
    space.Representation = model.create_entity(
        "IfcProductDefinitionShape",
        Representations=[_box_body_rep(model, body_context, room_l, room_h, room_w)],
    )
    run("aggregate.assign_object", model, relating_object=storey, products=[space])

    # Furnishings — one per object.
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "object").lower()
        ifc_class = _type_to_ifc_class(otype)
        name = obj.get("id") or otype
        item = run("root.create_entity", model, ifc_class=ifc_class, name=name)

        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        # Place at world X/Z; IFC uses Z-up so our "y" (height) becomes Z and graph z becomes Y.
        cx = float(pos.get("x", 0))
        cy = float(pos.get("z", 0))
        cz = float(pos.get("y", 0) or 0)
        item.ObjectPlacement = _make_local_placement(
            model, cx - l / 2, cy - w / 2, cz, relative_to=space.ObjectPlacement
        )
        item.Representation = model.create_entity(
            "IfcProductDefinitionShape",
            Representations=[_box_body_rep(model, body_context, l, h, w)],
        )
        run("spatial.assign_container", model, relating_structure=space, products=[item])

        # Property set with material + source.
        material_name = obj.get("material") or "unspecified"
        pset = run("pset.add_pset", model, product=item, name="KATHA_Design")
        run(
            "pset.edit_pset",
            model,
            pset=pset,
            properties={
                "ObjectType": otype,
                "SourceMaterial": material_name,
                "Length_m": round(l, 3),
                "Width_m": round(w, 3),
                "Height_m": round(h, 3),
            },
        )

    # Write to bytes via temp file (ifcopenshell serialises text).
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("wb", suffix=".ifc", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        model.write(tmp_path)
        data = Path(tmp_path).read_bytes()
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    return {
        "content_type": "application/x-step",
        "filename": f"{_safe_name(project_name)}-model.ifc",
        "bytes": data,
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
