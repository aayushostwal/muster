"""Tests for task creation, messaging, and lifecycle actions.

process_manager methods are monkeypatched with AsyncMocks: the real
process_manager (backend/app/services/process_manager.py) spawns actual
agent subprocesses and is owned/implemented by another agent concurrently,
so these tests only assert that the routes call into it correctly.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects, tasks
from app.db.session import get_db


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_create_task_becomes_queued_and_triggers_process_manager(
    override_get_db, monkeypatch
):
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/projects",
            json={"name": "Demo Project", "default_backend": "claude_code"},
        )
        assert resp.status_code == 201
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "title": "Do the thing",
                "initial_prompt": "please do the thing",
                "tags": ["PR Raised", "Canvas", "pr RAISED"],
            },
        )
        assert resp.status_code == 201
        task = resp.json()
        assert task["status"] == "queued"
        assert task["backend"] == "claude_code"
        assert task["project_id"] == project_id
        assert task["tags"] == ["PR Raised", "Canvas"]

        trigger_mock.assert_awaited_once()
        awaited_task_id = trigger_mock.await_args.args[0]
        assert str(awaited_task_id) == task["id"]

        # listing tasks for the project shows it
        resp = await client.get(f"/api/projects/{project_id}/tasks")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        # the global command center can see tasks without per-project fan-out
        resp = await client.get("/api/tasks")
        assert resp.status_code == 200
        assert [item["id"] for item in resp.json()["items"]] == [task["id"]]
        resp = await client.get("/api/tasks", params={"status": "queued"})
        assert [item["id"] for item in resp.json()["items"]] == [task["id"]]
        resp = await client.get("/api/tasks", params={"status": "done"})
        assert resp.json()["items"] == []

        # filtering by status
        resp = await client.get(
            f"/api/projects/{project_id}/tasks", params={"status": "queued"}
        )
        assert len(resp.json()["items"]) == 1
        resp = await client.get(
            f"/api/projects/{project_id}/tasks", params={"status": "done"}
        )
        assert len(resp.json()["items"]) == 0

        # getting the task directly
        resp = await client.get(f"/api/tasks/{task['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task["id"]

        resp = await client.patch(
            f"/api/tasks/{task['id']}/tags",
            json={"tags": ["PR Reviewed", "Canvas"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["PR Reviewed", "Canvas"]


@pytest.mark.asyncio
async def test_posting_a_message_persists_it_and_triggers_process_manager(
    override_get_db, monkeypatch
):
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/projects",
            json={"name": "Demo Project", "default_backend": "claude_code"},
        )
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "Do the thing", "initial_prompt": "please do the thing"},
        )
        task_id = resp.json()["id"]
        assert trigger_mock.await_count == 1

        canvas = {
            "kind": "magic_canvas",
            "title": "Login PRD",
            "format": "markdown",
            "language": "markdown",
            "content": "# Login PRD\n\nCurrent source of truth.",
        }
        resp = await client.post(
            f"/api/tasks/{task_id}/messages",
            json={"content_text": "here is more context", "media": [canvas]},
        )
        assert resp.status_code == 201
        message = resp.json()
        assert message["sender"] == "user"
        assert message["content_text"] == "here is more context"
        assert message["media"] == [canvas]
        assert message["task_id"] == task_id

        # trigger called again for the follow-up message
        assert trigger_mock.await_count == 2

        resp = await client.get(f"/api/tasks/{task_id}/messages")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

        db_generator = override_get_db()
        db = await anext(db_generator)
        try:
            enriched_prompt = await process_manager._latest_user_prompt_db(
                db, uuid.UUID(task_id)
            )
        finally:
            await db_generator.aclose()
        assert enriched_prompt is not None
        assert enriched_prompt.startswith("here is more context")
        assert "absolute source of truth" in enriched_prompt
        assert "Current source of truth." in enriched_prompt


@pytest.mark.asyncio
async def test_restart_uses_fresh_session_lifecycle_operation(override_get_db, monkeypatch):
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    restart_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)
    monkeypatch.setattr(process_manager, "restart_from_beginning", restart_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await client.post(
            "/api/projects",
            json={"name": "Demo Project", "default_backend": "claude_code"},
        )
        task = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Start again", "initial_prompt": "the original brief"},
        )
        task_id = task.json()["id"]

        response = await client.post(f"/api/tasks/{task_id}/restart")

    assert response.status_code == 200
    restart_mock.assert_awaited_once_with(uuid.UUID(task_id))
    assert trigger_mock.await_count == 1  # creation only; restart owns its spawn atomically
