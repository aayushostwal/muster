"""WebSocket endpoint for per-task live updates (see docs/SPEC.md "WebSocket").

Server -> client, one JSON event per message:
    {"type": "message", "message": {...Message...}}
    {"type": "status", "status": "running"}
    {"type": "run_attempt", "attempt": {...TaskRunAttempt...}}
    {"type": "token_usage", "used": 12000, "limit": 200000}

Client -> server is not used for sending chat (that's the durable REST POST
path); reserved for future typing indicators, so inbound frames are simply
drained.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# One entry per task with at least one open socket.
_connections: dict[uuid.UUID, set[WebSocket]] = {}


@router.websocket("/ws/tasks/{task_id}")
async def task_socket(websocket: WebSocket, task_id: uuid.UUID) -> None:
    await websocket.accept()
    _connections.setdefault(task_id, set()).add(websocket)
    try:
        while True:
            # No client->server protocol yet; just detect disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - any socket-level error ends the connection
        logger.debug("websocket for task %s closed with error", task_id, exc_info=True)
    finally:
        conns = _connections.get(task_id)
        if conns is not None:
            conns.discard(websocket)
            if not conns:
                _connections.pop(task_id, None)


async def broadcast(task_id: uuid.UUID, event: dict) -> None:
    """Forward `event` to every websocket currently connected for task_id.

    Called by process_manager after persisting each Message / status change /
    TaskRunAttempt (see docs/SPEC.md "Integration seams"). Safe to call when
    no one is connected -- it's just a no-op then.
    """
    conns = _connections.get(task_id)
    if not conns:
        return
    stale: list[WebSocket] = []
    for ws in list(conns):
        try:
            await ws.send_json(event)
        except Exception:  # noqa: BLE001 - dead/broken socket, drop it
            stale.append(ws)
    for ws in stale:
        conns.discard(ws)
    if not conns:
        _connections.pop(task_id, None)
