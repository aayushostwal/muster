"""WebSocket endpoints for live updates (see docs/SPEC.md "WebSocket").

Per-task feed (`/ws/tasks/{task_id}`), one JSON event per message:
    {"type": "message", "message": {...Message...}}
    {"type": "status", "status": "running"}
    {"type": "run_attempt", "attempt": {...TaskRunAttempt...}}
    {"type": "token_usage", "used": 12000, "limit": 200000}

Global feed (`/ws/events`), for cross-task notifications regardless of which
task (if any) a client currently has open:
    {"type": "task_status", "task_id": "...", "project_id": "...",
     "task_title": "...", "project_name": "...", "status": "running"}

Client -> server is not used for sending chat (that's the durable REST POST
path); reserved for future typing indicators, so inbound frames are simply
drained.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Task
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

# One entry per task with at least one open socket.
_connections: dict[uuid.UUID, set[WebSocket]] = {}

# Sockets subscribed to the cross-task status feed (not scoped to one task).
_global_connections: set[WebSocket] = set()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    _global_connections.add(websocket)
    try:
        while True:
            # No client->server protocol; just detect disconnects promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - any socket-level error ends the connection
        logger.debug("global events websocket closed with error", exc_info=True)
    finally:
        _global_connections.discard(websocket)


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

    Status events are additionally fanned out on the global `/ws/events` feed
    (enriched with task/project names) so clients not currently viewing this
    task can still surface a notification.
    """
    conns = _connections.get(task_id)
    if conns:
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

    if event.get("type") == "status":
        await _broadcast_status_globally(task_id, event["status"])


async def broadcast_global(event: dict) -> None:
    """Forward `event` to every websocket connected on the global feed."""
    if not _global_connections:
        return
    stale: list[WebSocket] = []
    for ws in list(_global_connections):
        try:
            await ws.send_json(event)
        except Exception:  # noqa: BLE001 - dead/broken socket, drop it
            stale.append(ws)
    for ws in stale:
        _global_connections.discard(ws)


async def _broadcast_status_globally(task_id: uuid.UUID, status: str) -> None:
    if not _global_connections:
        return  # avoid the DB round-trip when nobody is listening
    async with SessionLocal() as db:
        result = await db.execute(
            select(Task).options(selectinload(Task.project)).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
    if task is None:
        return
    await broadcast_global(
        {
            "type": "task_status",
            "task_id": str(task.id),
            "project_id": str(task.project_id),
            "task_title": task.title,
            "project_name": task.project.name if task.project else None,
            "status": status,
        }
    )
