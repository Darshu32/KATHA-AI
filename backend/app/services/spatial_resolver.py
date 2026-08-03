"""Resolve the loose DesignGraph into the typed ``SpatialModel``.

One deterministic upgrade path (no LLM): read the normalized graph and produce
the canonical typed spatial structures. Walls + openings come from the shared
``wall_model`` so they match the IFC export and section/elevation drawings
exactly; interior vs exterior is classified the same way the geometry kernel
does (a room-scale envelope with no site/building-scale objects).
"""

from __future__ import annotations

from app.models.spatial_spec import (
    Adjacency,
    Constraint,
    Dimensions,
    Opening,
    RoomEnvelope,
    SpatialModel,
    SpatialObject,
    Vec3,
    Wall,
)
from app.services.wall_model import derive_wall_model

_UNIT = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "metre": 1.0, "meter": 1.0,
         "ft": 0.3048, "feet": 0.3048, "in": 0.0254}
# Object types that mean "this is a site/building, not a room".
_SITE_TYPES = {"building", "tower", "block", "site", "plot", "driveway", "road",
               "parking", "landscape", "bridge", "pavilion"}
_CONSTRAINT_KINDS = {"coincident", "align_x", "align_z", "distance", "angle", "fixed"}


def _to_m(value, unit: str | None = None) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if unit:
        return n * _UNIT.get(str(unit).strip().lower(), 1.0)
    return n / 1000.0 if abs(n) > 30 else n


def _room_dims(graph: dict) -> tuple[float, float, float]:
    spaces = graph.get("spaces")
    if isinstance(spaces, list) and spaces and isinstance(spaces[0], dict):
        space = spaces[0]
    elif isinstance(graph.get("room"), dict):
        space = graph["room"]
    else:
        space = {}
    d = space.get("dimensions") if isinstance(space, dict) else None
    d = d if isinstance(d, dict) else {}
    u = d.get("unit")
    return (_to_m(d.get("length"), u), _to_m(d.get("width"), u), _to_m(d.get("height"), u) or 2.8)


def _is_interior(graph: dict, length: float, width: float, height: float) -> bool:
    if not (0.5 < length <= 30 and 0.5 < width <= 30):
        return False
    if not (0.0 < height <= 5.0):  # a 12 m "space" is a site, not a room
        return False
    for o in graph.get("objects") or []:
        if isinstance(o, dict) and str(o.get("type", "")).lower() in _SITE_TYPES:
            return False
    return True


def _constraints(graph: dict) -> list[Constraint]:
    out: list[Constraint] = []
    for c in graph.get("constraints") or []:
        if isinstance(c, dict) and c.get("kind") in _CONSTRAINT_KINDS:
            try:
                out.append(Constraint(
                    kind=c["kind"],
                    refs=[str(r) for r in (c.get("refs") or [])],
                    value=c.get("value"),
                ))
            except Exception:  # noqa: BLE001 — a malformed constraint is skipped, not fatal
                continue
    return out


def resolve_spatial_model(graph: dict) -> SpatialModel:
    """Loose DesignGraph → typed :class:`SpatialModel`."""
    graph = graph or {}
    length, width, height = _room_dims(graph)
    interior = _is_interior(graph, length, width, height)

    walls: list[Wall] = []
    opening_ids: set[str] = set()
    room: RoomEnvelope | None = None
    thickness = 0.15

    if interior:
        wm = derive_wall_model(graph)
        room = RoomEnvelope(**wm["room"])
        thickness = float(wm["thickness"])
        for w in wm["walls"]:
            openings = [
                Opening(source_id=str(o["source_id"]), kind=o["kind"], center=o["center"],
                        width=o["width"], sill=o["sill"], head=o["head"])
                for o in w["openings"]
            ]
            opening_ids.update(o.source_id for o in openings)
            walls.append(Wall(
                id=str(w["id"]), side=w["side"], runs=w["runs"], at=w["at"],
                length=w["length"], height=w["height"], thickness=w["thickness"],
                openings=openings,
            ))

    objects: list[SpatialObject] = []
    for obj in graph.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        oid = str(obj.get("id") or obj.get("name") or "obj")
        if oid in opening_ids:  # became a wall opening, not a standalone object
            continue
        d = obj.get("dimensions") or {}
        u = d.get("unit")
        p = obj.get("position") or {}
        mat = obj.get("material")
        objects.append(SpatialObject(
            id=oid,
            type=str(obj.get("type") or "object"),
            role=str(obj.get("role") or "furniture"),
            position=Vec3(x=float(p.get("x", 0) or 0), y=float(p.get("y", 0) or 0), z=float(p.get("z", 0) or 0)),
            dimensions=Dimensions(
                length=_to_m(d.get("length"), u),
                width=_to_m(d.get("width"), u),
                height=_to_m(d.get("height"), u),
            ),
            rotation_y=float((obj.get("rotation") or {}).get("y", 0) or 0),
            material=mat if isinstance(mat, str) else None,
        ))

    # Basic circulation seed: every opening connects the room to the outside.
    adjacencies = [Adjacency(a="room", b="outside", via=o.source_id) for w in walls for o in w.openings]

    return SpatialModel(
        kind="interior" if interior else "exterior",
        room=room,
        thickness=thickness,
        walls=walls,
        objects=objects,
        adjacencies=adjacencies,
        constraints=_constraints(graph),
    )
