from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects, tasks
from app.config import settings
from app.db.session import get_db
from app.services.process_manager import process_manager


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_manual_task_uses_configured_interactive_default(override_get_db, monkeypatch):
    monkeypatch.setattr(settings, "interactive_terminal_enabled", True)
    monkeypatch.setattr(settings, "default_task_runtime_mode", "interactive")
    trigger = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    app = _build_app(override_get_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = await client.post(
            "/api/projects", json={"name": "Terminal project", "default_backend": "codex"}
        )
        task = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Interactive", "initial_prompt": "Open the TUI"},
        )

    assert task.status_code == 201
    assert task.json()["runtime_mode"] == "interactive"
    trigger.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_interactive_task_is_rejected_when_disabled(override_get_db, monkeypatch):
    monkeypatch.setattr(settings, "interactive_terminal_enabled", False)
    trigger = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger)
    app = _build_app(override_get_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = await client.post(
            "/api/projects", json={"name": "Terminal project", "default_backend": "codex"}
        )
        task = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={
                "title": "Interactive",
                "initial_prompt": "Open the TUI",
                "runtime_mode": "interactive",
            },
        )

    assert task.status_code == 422
    assert "disabled" in task.json()["detail"].lower()
    trigger.assert_not_awaited()
