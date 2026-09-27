from __future__ import annotations

import asyncio
import base64
import threading
import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routes import terminal_ws
from app.config import settings
from app.services.process_manager import terminal_manager


def test_terminal_websocket_attaches_and_forwards_input(monkeypatch):
    monkeypatch.setattr(settings, "interactive_terminal_enabled", True)
    queue: asyncio.Queue[dict] = asyncio.Queue()
    queue.put_nowait(
        {"type": "ready", "session": "session-1", "control": "granted", "oldest_seq": 1, "latest_seq": 0}
    )
    attach = AsyncMock(return_value=("client-1", queue))
    send_input = AsyncMock()
    detached = threading.Event()
    detach = AsyncMock(side_effect=lambda *_: detached.set())
    monkeypatch.setattr(terminal_manager, "attach", attach)
    monkeypatch.setattr(terminal_manager, "input", send_input)
    monkeypatch.setattr(terminal_manager, "detach", detach)
    app = FastAPI()
    app.include_router(terminal_ws.router)
    task_id = uuid.uuid4()

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/tasks/{task_id}/terminal", headers={"origin": "http://localhost:3000"}
        ) as websocket:
            websocket.send_json({"type": "attach", "cols": 90, "rows": 28, "after_seq": 0})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {"type": "input", "data_b64": base64.b64encode(b"hello").decode("ascii")}
            )

    attach.assert_awaited_once_with(task_id, cols=90, rows=28, after_seq=0)
    send_input.assert_awaited_once_with(task_id, "client-1", b"hello")
    assert detached.wait(timeout=1), "terminal websocket did not detach"
    detach.assert_awaited_once_with(task_id, "client-1")


def test_terminal_websocket_rejects_disallowed_origin(monkeypatch):
    monkeypatch.setattr(settings, "interactive_terminal_enabled", True)
    app = FastAPI()
    app.include_router(terminal_ws.router)

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                f"/ws/tasks/{uuid.uuid4()}/terminal", headers={"origin": "https://evil.example"}
            ):
                raise AssertionError("disallowed terminal origin connected")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
