"""Collaborative editing websocket — Yjs sync for the design workspace.

``GET /api/v1/ws/design/{project_id}?token=<jwt>`` upgrades to a websocket and
joins the project's shared room (see ``app.services.collab``). Auth is via a
query-param token because browsers can't set Authorization headers on a
WebSocket; ownership is checked before the upgrade, mirroring the REST routes.
"""

import logging

from fastapi import APIRouter, Query, WebSocket, status
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.database import async_session_factory
from app.models.orm import User
from app.services.auth_service import decode_access_token, get_or_create_dev_user
from app.services.collab import (
    StarletteYChannel,
    get_seeded_room,
    persist_room,
    room_name,
    websocket_server,
)
from app.services.design_graph_service import get_latest_version, get_project

logger = logging.getLogger(__name__)

router = APIRouter()


async def _authorize(project_id: str, token: str):
    """Resolve (user, graph) for the token, or (None, None) if unauthorized.

    Parity with ``get_current_user``: a valid token resolves its user; no token
    falls back to the dev user (local dev). Ownership is enforced by the caller.
    """
    async with async_session_factory() as db:
        user = None
        if token:
            user_id = decode_access_token(token)
            if user_id:
                user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None and not token:
            user = await get_or_create_dev_user(db)
        if user is None or not user.is_active:
            return None, None
        project = await get_project(db, project_id)
        if project is None or project.owner_id != user.id:
            return None, None
        version = await get_latest_version(db, project_id)
        return user, (version.graph_data if version else {})


@router.websocket("/ws/design/{project_id}")
async def design_ws(websocket: WebSocket, project_id: str, token: str = Query(default="")):
    user, graph = await _authorize(project_id, token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    room = await get_seeded_room(project_id, graph or {})
    channel = StarletteYChannel(websocket, path=room_name(project_id))
    try:
        await websocket_server.serve(channel)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — never let one client crash the room
        logger.warning("collab serve error (%s): %s", project_id, exc)
    finally:
        try:
            await persist_room(project_id, room)
        except Exception as exc:  # noqa: BLE001
            logger.warning("collab persist failed (%s): %s", project_id, exc)
