"""Bidirectional, local-only WebSocket bridge for interactive task PTYs."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.services.process_manager import terminal_manager

router = APIRouter()


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict]) -> None:
    while True:
        event = await queue.get()
        await websocket.send_json(event)
        if event.get("type") == "error" and event.get("code") == "slow_client":
            await websocket.close(code=1013)
            return


@router.websocket("/ws/tasks/{task_id}/terminal")
async def task_terminal_socket(websocket: WebSocket, task_id: uuid.UUID) -> None:
    origin = websocket.headers.get("origin")
    host = websocket.client.host if websocket.client else None
    if (
        not settings.interactive_terminal_enabled
        or not _is_loopback(host)
        or (origin is not None and origin not in settings.terminal_allowed_origin_set)
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    client_id: str | None = None
    sender: asyncio.Task | None = None
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if first.get("type") != "attach":
            await websocket.send_json(
                {"type": "error", "code": "attach_required", "message": "First frame must attach"}
            )
            await websocket.close(code=1008)
            return
        cols = _bounded_int(first.get("cols"), 120, 20, 500)
        rows = _bounded_int(first.get("rows"), 32, 5, 200)
        after_seq = _bounded_int(first.get("after_seq"), 0, 0, 2**63 - 1)
        try:
            client_id, queue = await terminal_manager.attach(
                task_id, cols=cols, rows=rows, after_seq=after_seq
            )
        except (KeyError, ValueError) as exc:
            await websocket.send_json(
                {"type": "error", "code": "session_unavailable", "message": str(exc)}
            )
            await websocket.close(code=1008)
            return
        sender = asyncio.create_task(_send_events(websocket, queue))

        while True:
            frame = await websocket.receive_json()
            frame_type = frame.get("type")
            if frame_type == "input":
                try:
                    data = base64.b64decode(frame.get("data_b64", ""), validate=True)
                except (binascii.Error, ValueError):
                    await websocket.send_json(
                        {"type": "error", "code": "invalid_input", "message": "Invalid base64 input"}
                    )
                    continue
                if len(data) > 64 * 1024:
                    await websocket.send_json(
                        {"type": "error", "code": "input_too_large", "message": "Input exceeds 64 KiB"}
                    )
                    continue
                try:
                    await terminal_manager.input(task_id, client_id, data)
                except (KeyError, PermissionError) as exc:
                    await websocket.send_json(
                        {"type": "error", "code": "read_only", "message": str(exc)}
                    )
            elif frame_type == "resize":
                await terminal_manager.resize(
                    task_id,
                    client_id,
                    _bounded_int(frame.get("cols"), 120, 20, 500),
                    _bounded_int(frame.get("rows"), 32, 5, 200),
                )
            elif frame_type == "take_control":
                try:
                    await terminal_manager.take_control(task_id, client_id)
                except KeyError as exc:
                    await websocket.send_json(
                        {"type": "error", "code": "session_unavailable", "message": str(exc)}
                    )
            elif frame_type in {"ack", "ping"}:
                continue
            else:
                await websocket.send_json(
                    {"type": "error", "code": "unknown_frame", "message": "Unknown terminal frame"}
                )
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        if sender is not None:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if client_id is not None:
            await terminal_manager.detach(task_id, client_id)


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
