"""Route-level tests for the task lifecycle refinement: explicit completion,
reopening, and restart. Mirrors test_tasks_api.py's convention of
monkeypatching process_manager methods with AsyncMocks and asserting the
routes call into them correctly -- the actual status-classification logic
lives in ProcessManager and is covered directly in
test_process_manager_lifecycle.py.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects, tasks
from app.db.models import Task, TaskStatus
from app.db.session import get_db


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


async def _create_project_and_task(client: AsyncClient) -> tuple[str, str]:
    resp = await client.post(
        "/api/projects", json={"name": "Demo Project", "default_backend": "claude_code"}
    )
    project_id = resp.json()["id"]
    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"title": "Do the thing", "initial_prompt": "please do the thing"},
    )
    return project_id, resp.json()["id"]


@pytest.mark.asyncio
async def test_complete_endpoint_calls_process_manager_complete(override_get_db, monkeypatch):
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    complete_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "complete", complete_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _, task_id = await _create_project_and_task(client)

        resp = await client.post(f"/api/tasks/{task_id}/complete")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

        complete_mock.assert_awaited_once()
        assert str(complete_mock.await_args.args[0]) == task_id


@pytest.mark.asyncio
async def test_restart_endpoint_delegates_the_full_reset_to_process_manager(
    override_get_db, monkeypatch
):
    """`/restart` used to reset status/session_id/timestamps in the route
    itself, then call trigger() -- two separate, unlocked writes. That reset
    now lives entirely inside ProcessManager.restart_from_beginning() so it's serialized
    with cancel()/complete()/trigger() under one per-task lock. The route
    should do nothing but delegate.
    """
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    restart_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "restart_from_beginning", restart_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _, task_id = await _create_project_and_task(client)

        resp = await client.post(f"/api/tasks/{task_id}/restart")
        assert resp.status_code == 200

        restart_mock.assert_awaited_once()
        assert str(restart_mock.await_args.args[0]) == task_id


@pytest.mark.asyncio
async def test_posting_a_message_delegates_atomic_resume_to_process_manager(
    override_get_db, monkeypatch
):
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)
    resume_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "resume", resume_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _, task_id = await _create_project_and_task(client)

        # Simulate the task having been closed out (e.g. via /complete or the
        # old auto-done exit) with a stale attention_reason left over.
        db_generator = override_get_db()
        db = await anext(db_generator)
        try:
            task = await db.get(Task, uuid.UUID(task_id))
            task.status = TaskStatus.done
            task.attention_reason = "awaiting_review"
            await db.commit()
        finally:
            await db_generator.aclose()

        resp = await client.post(
            f"/api/tasks/{task_id}/messages", json={"content_text": "one more thing"}
        )
        assert resp.status_code == 201
        resume_mock.assert_awaited_once_with(uuid.UUID(task_id))
        # Creation still uses trigger(); follow-ups use the atomic resume path.
        trigger_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_rapid_repeat_cancel_calls_are_each_forwarded_and_do_not_error(
    override_get_db, monkeypatch
):
    """A rapid double-click on "Cancel" should hit the route twice; neither
    call should error, and both should reach the process manager -- actual
    idempotence is ProcessManager.cancel()'s job (covered separately), this
    just proves the route layer imposes no unsafe assumptions.
    """
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    cancel_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "cancel", cancel_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        _, task_id = await _create_project_and_task(client)

        first = await client.post(f"/api/tasks/{task_id}/cancel")
        second = await client.post(f"/api/tasks/{task_id}/cancel")
        assert first.status_code == 200
        assert second.status_code == 200
        assert cancel_mock.await_count == 2
