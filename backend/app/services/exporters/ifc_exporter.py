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

from app.services.graph_normalizer import normalize_graph
from app.services.wall_model import derive_multiroom_wall_model, derive_wall_model


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


def _place_box(model, body_context, storey, ifc_class, name, loc, xdim, ydim, depth):
    """Create an entity as an axis-aligned box (XDim×YDim, extruded Depth in Z)."""
    ent = run("root.create_entity", model, ifc_class=ifc_class, name=name)
    ent.ObjectPlacement = _make_local_placement(
        model, loc[0], loc[1], loc[2], relative_to=storey.ObjectPlacement
    )
    ent.Representation = model.create_entity(
        "IfcProductDefinitionShape",
        Representations=[_box_body_rep(model, body_context, xdim, depth, ydim)],
    )
    return ent


def _add_walls_with_openings(model, body_context, storey, space, graph, room_h):
    """Build the four perimeter walls and void them with real window/door openings.

    Reads the shared ``wall_model`` (same source the section/elevation drawings
    use) so a window is an ``IfcOpeningElement`` that *voids* the wall and is
    *filled* by an ``IfcWindow`` — not a floating box. Opens as coordinated
    geometry in Revit / ArchiCAD.
    """
    model_walls = derive_wall_model(graph)
    t = float(model_walls["thickness"])
    L = float(model_walls["room"]["length"])
    W = float(model_walls["room"]["width"])
    H = float(room_h)

    # (side, centre X, centre Y, XDim, YDim) — walls centred on their line, Z 0→H.
    layout = {
        "south": (L / 2, 0.0, L, t),
        "north": (L / 2, W, L, t),
        "west": (0.0, W / 2, t, W),
        "east": (L, W / 2, t, W),
    }
    walls_by_side: dict[str, object] = {}
    for side, (cx, cy, xdim, ydim) in layout.items():
        wall = _place_box(model, body_context, storey, "IfcWall", f"Wall {side.title()}", (cx, cy, 0.0), xdim, ydim, H)
        run("spatial.assign_container", model, relating_structure=storey, products=[wall])
        pset = run("pset.add_pset", model, product=wall, name="KATHA_Design")
        run("pset.edit_pset", model, pset=pset, properties={"ObjectType": "wall", "Side": side, "Thickness_m": round(t, 3), "Height_m": round(H, 3)})
        walls_by_side[side] = wall

    for wall_spec in model_walls["walls"]:
        side = wall_spec["side"]
        wall = walls_by_side[side]
        for op in wall_spec["openings"]:
            c, w = float(op["center"]), float(op["width"])
            sill, head = float(op["sill"]), float(op["head"])
            oh = max(head - sill, 0.05)
            if side in ("south", "north"):
                at_y = 0.0 if side == "south" else W
                op_loc, op_x, op_y = (c, at_y, sill), w, t * 1.6
                fill_x, fill_y = w, max(t * 0.4, 0.05)
            else:
                at_x = 0.0 if side == "west" else L
                op_loc, op_x, op_y = (at_x, c, sill), t * 1.6, w
                fill_x, fill_y = max(t * 0.4, 0.05), w

            opening = _place_box(model, body_context, storey, "IfcOpeningElement", f"Opening {op['source_id']}", op_loc, op_x, op_y, oh)
            run("feature.add_feature", model, feature=opening, element=wall)

            fill_class = "IfcWindow" if op["kind"] == "window" else "IfcDoor"
            filling = _place_box(model, body_context, storey, fill_class, op["source_id"], op_loc, fill_x, fill_y, oh)
            run("feature.add_filling", model, opening=opening, element=filling)
            pset = run("pset.add_pset", model, product=filling, name="KATHA_Design")
            run("pset.edit_pset", model, pset=pset, properties={"ObjectType": op["kind"], "Wall": side, "Width_m": round(w, 3), "Sill_m": round(sill, 3), "Head_m": round(head, 3)})

    return {"walls": len(walls_by_side), "openings": sum(len(w["openings"]) for w in model_walls["walls"])}


def _placed_rooms(graph: dict) -> list[dict]:
    """Spaces carrying an explicit position + dimensions → room dicts (metres).

    Two or more switch ``export`` onto the multi-room path (one IfcSpace each).
    Empty for a single unsolved room → the perimeter-wall path applies.
    """
    out: list[dict] = []
    for i, s in enumerate(graph.get("spaces") or []):
        if not isinstance(s, dict):
            continue
        pos, d = s.get("position"), s.get("dimensions")
        if not (isinstance(pos, dict) and isinstance(d, dict)):
            continue
        L, Wd = _m(d.get("length")), _m(d.get("width"))
        if L <= 0 or Wd <= 0:
            continue
        out.append({
            "id": str(s.get("id") or s.get("name") or f"space_{i + 1}"),
            "name": str(s.get("name") or s.get("id") or f"Room {i + 1}"),
            "x": float(pos.get("x", 0) or 0), "z": float(pos.get("z", 0) or 0),
            "length": L, "width": Wd, "height": _m(d.get("height")) or 3.0,
        })
    return out


def _add_multiroom_spaces_and_walls(model, body_context, storey, rooms: list[dict], adjacencies=None) -> dict:
    """One IfcSpace per room + partition/exterior IfcWalls (Stage D), with real
    openings — doors in partitions between adjacent rooms, windows on exterior
    walls, each an ``IfcOpeningElement`` voiding the wall and *filled* by an
    ``IfcDoor``/``IfcWindow``. Coordinates: graph x→IFC X, graph z→IFC Y,
    height→IFC Z. Box profiles are centred on their placement."""
    for r in rooms:
        L, W, H = r["length"], r["width"], r["height"]
        space = run("root.create_entity", model, ifc_class="IfcSpace", name=r["name"])
        space.ObjectPlacement = _make_local_placement(
            model, r["x"] + L / 2, r["z"] + W / 2, 0.0, relative_to=storey.ObjectPlacement
        )
        space.Representation = model.create_entity(
            "IfcProductDefinitionShape",
            Representations=[_box_body_rep(model, body_context, L, H, W)],
        )
        run("aggregate.assign_object", model, relating_object=storey, products=[space])
        pset = run("pset.add_pset", model, product=space, name="KATHA_Design")
        run("pset.edit_pset", model, pset=pset,
            properties={"ObjectType": "room", "Room": r["id"], "Area_m2": round(L * W, 2), "Height_m": round(H, 3)})

    segments = derive_multiroom_wall_model(rooms, adjacencies)
    openings = 0
    for seg in segments:
        length = max(seg["end"] - seg["start"], 1e-3)
        if seg["runs"] == "z":            # vertical wall: thin in X, long in Y
            xdim, ydim, cx, cy = seg["thickness"], length, seg["at"], (seg["start"] + seg["end"]) / 2
        else:                              # horizontal wall: long in X, thin in Y
            xdim, ydim, cx, cy = length, seg["thickness"], (seg["start"] + seg["end"]) / 2, seg["at"]
        wall = _place_box(model, body_context, storey, "IfcWall",
                          f"Wall {'/'.join(seg['rooms'])}", (cx, cy, 0.0), xdim, ydim, seg["height"])
        run("spatial.assign_container", model, relating_structure=storey, products=[wall])
        pset = run("pset.add_pset", model, product=wall, name="KATHA_Design")
        run("pset.edit_pset", model, pset=pset, properties={
            "ObjectType": "wall", "Kind": seg["kind"], "Rooms": ",".join(seg["rooms"]),
            "Thickness_m": round(seg["thickness"], 3), "Height_m": round(seg["height"], 3)})

        t = seg["thickness"]
        for op in seg.get("openings", []):
            c = seg["start"] + op["center"]        # absolute along the run axis
            w, sill = op["width"], op["sill"]
            oh = max(op["head"] - sill, 0.05)
            if seg["runs"] == "z":                 # void through X (wall thin in X)
                loc, void_x, void_y, fill_x, fill_y = (seg["at"], c, sill), t * 1.6, w, max(t * 0.4, 0.05), w
            else:                                   # void through Y (wall thin in Y)
                loc, void_x, void_y, fill_x, fill_y = (c, seg["at"], sill), w, t * 1.6, w, max(t * 0.4, 0.05)
            opening = _place_box(model, body_context, storey, "IfcOpeningElement",
                                 f"Opening {op['source_id']}", loc, void_x, void_y, oh)
            run("feature.add_feature", model, feature=opening, element=wall)
            fill_class = "IfcWindow" if op["kind"] == "window" else "IfcDoor"
            filling = _place_box(model, body_context, storey, fill_class, op["source_id"], loc, fill_x, fill_y, oh)
            run("feature.add_filling", model, opening=opening, element=filling)
            fpset = run("pset.add_pset", model, product=filling, name="KATHA_Design")
            run("pset.edit_pset", model, pset=fpset, properties={
                "ObjectType": op["kind"], "Wall": seg["id"],
                "Width_m": round(w, 3), "Sill_m": round(sill, 3), "Head_m": round(op["head"], 3)})
            openings += 1
    return {"spaces": len(rooms), "walls": len(segments), "openings": openings}


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"
    # Capture adjacencies before normalization (which may not preserve them) so
    # multi-room door placement survives.
    adjacencies = (graph or {}).get("adjacencies")
    # Defensive, idempotent normalization so units/axes and the derived walls
    # are correct even for legacy or un-normalized graphs (mirrors the drawing
    # routes' read-time normalization).
    graph, _ = normalize_graph(graph or {})
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

    # Space(s) + walls. A solved multi-room plan (≥2 placed rooms) gets one
    # IfcSpace per room and partition/exterior walls; otherwise the single room
    # keeps its four perimeter walls with real window/door voids.
    placed = _placed_rooms(graph)
    if len(placed) >= 2:
        _add_multiroom_spaces_and_walls(model, body_context, storey, placed, adjacencies)
        container = storey  # furnishings attach to the storey
    else:
        space = run("root.create_entity", model, ifc_class="IfcSpace", name=(room.get("type") or "Room"))
        space.ObjectPlacement = _make_local_placement(model, 0, 0, 0, relative_to=storey.ObjectPlacement)
        space.Representation = model.create_entity(
            "IfcProductDefinitionShape",
            Representations=[_box_body_rep(model, body_context, room_l, room_h, room_w)],
        )
        run("aggregate.assign_object", model, relating_object=storey, products=[space])
        _add_walls_with_openings(model, body_context, storey, space, graph, room_h)
        container = space

    # Furnishings — one per object. Windows / doors / walls are handled by the
    # wall model above (as fillings / walls), so skip them here to avoid
    # duplicate, unrelated boxes.
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "object").lower()
        role = str(obj.get("role") or "").lower()
        ifc_class = _type_to_ifc_class(otype)
        if role in {"window", "door", "wall"} or ifc_class in {"IfcWindow", "IfcDoor", "IfcWall"}:
            continue
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
            model, cx - l / 2, cy - w / 2, cz, relative_to=container.ObjectPlacement
        )
        item.Representation = model.create_entity(
            "IfcProductDefinitionShape",
            Representations=[_box_body_rep(model, body_context, l, h, w)],
        )
        run("spatial.assign_container", model, relating_structure=container, products=[item])

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
