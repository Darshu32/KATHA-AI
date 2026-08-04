"""Real-time collaborative editing — Yjs CRDT sync over a FastAPI websocket.

The design's editable state lives in a per-project shared ``pycrdt.Doc`` (a
"room"): a ``Y.Map`` named ``objects`` mapping each object id to a ``Y.Map`` of
its ``{x, y, z}`` position. Browser clients connect via y-websocket and edit the
same map, so a drag in one tab appears live in another. Each room is seeded from
the latest saved version on first open and snapshotted back to the DB when a
client disconnects. Positions-first slice — dimensions / constraints can follow.

Transport is pycrdt-websocket (Rust-backed Yjs for Python) mounted on the
existing FastAPI app, so there's no separate Node sync service to run.
"""

from __future__ import annotations

import logging

from pycrdt import Map
from pycrdt.websocket import WebsocketServer
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# One server for the whole app; started/stopped in the FastAPI lifespan.
# auto_clean_rooms=False keeps a room's Doc alive across brief disconnects (the
# in-memory Doc holds one entry per opened project; the DB is the durable store).
websocket_server = WebsocketServer(auto_clean_rooms=False)

ROOM_PREFIX = "design:"


def room_name(project_id: str) -> str:
    return f"{ROOM_PREFIX}{project_id}"


class StarletteYChannel:
    """Adapt a Starlette/FastAPI WebSocket to pycrdt-websocket's Channel protocol
    (``path`` + async-iterable ``recv`` + ``send``)."""

    def __init__(self, websocket: WebSocket, path: str):
        self._ws = websocket
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def __aiter__(self) -> "StarletteYChannel":
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self.recv()
        except WebSocketDisconnect as exc:  # noqa: F841
            raise StopAsyncIteration from None

    async def send(self, message: bytes) -> None:
        await self._ws.send_bytes(message)

    async def recv(self) -> bytes:
        return await self._ws.receive_bytes()


def _positions_from_graph(graph: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for o in graph.get("objects") or []:
        oid = o.get("id")
        if not oid:
            continue
        pos = o.get("position") or {}
        out[str(oid)] = {
            "x": float(pos.get("x", 0) or 0),
            "y": float(pos.get("y", 0) or 0),
            "z": float(pos.get("z", 0) or 0),
        }
    return out


async def get_seeded_room(project_id: str, graph: dict):
    """Get/create the project's room, seeding its Doc from ``graph`` when empty
    (first opener). Later openers sync from the live Doc."""
    room = await websocket_server.get_room(room_name(project_id))
    objects = room.ydoc.get("objects", type=Map)
    if len(objects) == 0:
        seed = _positions_from_graph(graph)
        if seed:
            with room.ydoc.transaction():
                for oid, p in seed.items():
                    objects[oid] = Map(p)
    return room


def snapshot_positions(room) -> dict[str, dict]:
    """Current object positions from the room Doc."""
    objects = room.ydoc.get("objects", type=Map)
    out: dict[str, dict] = {}
    for oid in list(objects.keys()):
        m = objects[oid]
        try:
            out[str(oid)] = {"x": float(m["x"]), "y": float(m["y"]), "z": float(m["z"])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def persist_room(project_id: str, room) -> bool:
    """Write the room's live positions back into the latest version's graph
    (in place, like the position PATCH). Returns True if anything changed."""
    positions = snapshot_positions(room)
    if not positions:
        return False

    from sqlalchemy.orm.attributes import flag_modified

    from app.database import async_session_factory
    from app.services.design_graph_service import get_latest_version

    async with async_session_factory() as db:
        version = await get_latest_version(db, project_id)
        if version is None:
            return False
        graph = version.graph_data or {}
        changed = False
        for o in graph.get("objects") or []:
            p = positions.get(str(o.get("id")))
            if p:
                o["position"] = {**(o.get("position") or {}), **p}
                changed = True
        if changed:
            flag_modified(version, "graph_data")
            await db.commit()
        return changed
