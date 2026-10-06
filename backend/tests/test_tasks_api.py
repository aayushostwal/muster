"""Tests for task creation, messaging, and lifecycle actions.

process_manager methods are monkeypatched with AsyncMocks: the real
process_manager (backend/app/services/process_manager.py) spawns actual
agent subprocesses and is owned/implemented by another agent concurrently,
so these tests only assert that the routes call into it correctly.
"""
from __future__ import annotations

import uuid
import os
import time
from pathlib import Path
from stat import S_IMODE
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects, task_attachments, tasks
from app.config import settings
from app.db.session import get_db
from app.db.models import Task


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(task_attachments.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_create_task_with_uploaded_image_and_file(
    override_get_db, monkeypatch, tmp_path
):
    from app.services.process_manager import process_manager
    from app.services.task_attachments import render_prompt
    from app.services import task_attachments as attachment_service
    from app.schemas.task import TaskAttachment

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    monkeypatch.setattr(process_manager, "cancel", AsyncMock())
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = await client.post(
            "/api/projects", json={"name": "Attachments", "default_backend": "claude_code"}
        )
        image = await client.post(
            "/api/task-attachments",
            files={"file": ("screen shot.png", b"png-data", "image/png")},
        )
        document = await client.post(
            "/api/task-attachments",
            files={"file": ("requirements.txt", b"details", "text/plain")},
        )
        assert image.status_code == 201
        assert document.status_code == 201
        assert render_prompt("plain", []) == "plain"

        tampered = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Tampered", "initial_prompt": "Bad metadata", "media": [{**image.json(), "size": 999}]},
        )
        assert tampered.status_code == 422

        response = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={
                "title": "Use the context",
                "initial_prompt": "Review the supplied material",
                "media": [image.json(), document.json()],
            },
        )
        assert response.status_code == 201
        task = response.json()
        assert [item["name"] for item in task["media"]] == ["screen shot.png", "requirements.txt"]
        assert "screen shot.png" in render_prompt(task["initial_prompt"], task["media"])
        assert task["media"][0]["path"] in render_prompt(task["initial_prompt"], task["media"])
        stored = Path(task["media"][0]["path"])
        assert S_IMODE(stored.stat().st_mode) == 0o400
        assert S_IMODE(stored.parent.stat().st_mode) == 0o500

        db_generator = override_get_db()
        db = await anext(db_generator)
        try:
            task_model = await db.get(Task, uuid.UUID(task["id"]))
            project_model = await process_manager._load_project(db, task_model.project_id)
            bindings = await process_manager._bindings_for(db, project_model, task_model)
        finally:
            await db_generator.aclose()
        assert str(stored.parent) in bindings.directories
        assert any(
            rule.get("decision") == "deny"
            and rule.get("claude_pattern") == f"Edit({stored.parent}/**)"
            for rule in bindings.tool_rules
        )

        reused = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Reuse", "initial_prompt": "Reuse file", "media": task["media"]},
        )
        assert reused.status_code == 409
        with pytest.raises(HTTPException, match="already assigned"):
            attachment_service.claim(task["media"], uuid.uuid4())
        with pytest.raises(HTTPException, match="not found"):
            attachment_service.resolve_download(uuid.uuid4(), "missing.txt")

        releasable = await client.post(
            "/api/task-attachments",
            files={"file": ("release.txt", b"release", "text/plain")},
        )
        release_media = attachment_service.validate([
            TaskAttachment.model_validate(releasable.json())
        ])
        release_task_id = uuid.uuid4()
        attachment_service.claim(release_media, release_task_id)
        attachment_service.release(release_media, release_task_id)
        release_path = Path(release_media[0]["path"])
        assert not (release_path.parent / ".claimed").exists()
        assert S_IMODE(release_path.stat().st_mode) == 0o600

        downloaded = await client.get(task["media"][0]["url"])
        assert downloaded.status_code == 200
        assert downloaded.content == b"png-data"

        assert (await client.delete(f"/api/tasks/{task['id']}")).status_code == 204
        assert not stored.parent.exists()


@pytest.mark.asyncio
async def test_create_task_rejects_unmanaged_attachment(override_get_db, monkeypatch, tmp_path):
    from app.services.process_manager import process_manager

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = await client.post(
            "/api/projects", json={"name": "Attachments", "default_backend": "codex"}
        )
        response = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={
                "title": "Unsafe",
                "initial_prompt": "Read arbitrary file",
                "media": [{"name": "passwd", "path": "/etc/passwd", "mime": "text/plain", "size": 1, "url": "/api/task-attachments/fake/passwd"}],
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_attachment_upload_enforces_storage_quota(monkeypatch, tmp_path):
    from app.services import task_attachments as service

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(service, "MAX_STORAGE_OBJECTS", 0)
    app = FastAPI()
    app.include_router(task_attachments.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        object_response = await client.post(
            "/api/task-attachments",
            files={"file": ("blocked.txt", b"x", "text/plain")},
        )
    assert object_response.status_code == 507

    monkeypatch.setattr(service, "MAX_STORAGE_OBJECTS", 1000)
    monkeypatch.setattr(service, "MAX_STORAGE_BYTES", 3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/task-attachments",
            files={"file": ("too-large.txt", b"four", "text/plain")},
        )
    assert response.status_code == 507
    assert list((tmp_path / "media" / "task-attachments").iterdir()) == []

    root = tmp_path / "media" / "task-attachments"
    expired = root / "expired"
    expired.mkdir()
    (expired / "old.txt").write_text("old")
    old = time.time() - service.PENDING_TTL_SECONDS - 1
    os.utime(expired, (old, old))
    claimed = root / "claimed"
    claimed.mkdir()
    (claimed / ".claimed").write_text("task")
    os.utime(claimed, (old, old))
    service.cleanup_expired_pending()
    assert not expired.exists()
    assert claimed.exists()


@pytest.mark.asyncio
async def test_attachment_upload_limits_request_before_multipart_parsing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    app = FastAPI()
    app.add_middleware(task_attachments.AttachmentUploadLimitMiddleware, max_bytes=10)
    app.include_router(task_attachments.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/task-attachments",
            files={"file": ("small.txt", b"x", "text/plain")},
        )
    assert response.status_code == 413

    app = FastAPI()
    app.add_middleware(task_attachments.AttachmentUploadLimitMiddleware, max_bytes=1024)
    app.include_router(task_attachments.router, prefix="/api")
    @app.get("/health")
    async def health():
        return {"ok": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        accepted = await client.post(
            "/api/task-attachments",
            files={"file": ("small.txt", b"x", "text/plain")},
        )
    assert accepted.status_code == 201

    async def consume(_scope, receive, _send):
        while (await receive()).get("more_body"):
            pass

    chunks = iter([
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ])
    sent = []
    async def capture(message):
        sent.append(message)
    middleware = task_attachments.AttachmentUploadLimitMiddleware(consume, max_bytes=3)
    await middleware(
        {"type": "http", "path": "/api/task-attachments", "headers": []},
        lambda: next_chunk(chunks),
        capture,
    )
    assert sent[0]["status"] == 413


async def next_chunk(chunks):
    return next(chunks)


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
                "tags": ["Bug", "Customer beta", "bug"],
            },
        )
        assert resp.status_code == 201
        task = resp.json()
        assert task["status"] == "queued"
        assert task["backend"] == "claude_code"
        assert task["project_id"] == project_id
        assert task["tags"] == ["Bug", "Customer beta"]

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
            json={"tags": ["Feature", "Customer beta"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["Feature", "Customer beta"]

        # Evidence-backed labels cannot be assigned through the generic tag API.
        resp = await client.patch(
            f"/api/tasks/{task['id']}/tags",
            json={"tags": ["PR Raised"]},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_portable_agent_does_not_override_task_runtime_or_model(
    override_get_db, db_engine, monkeypatch
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentBackend, AgentProfile
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = await client.post(
            "/api/projects",
            json={
                "name": "Portable profiles",
                "default_backend": "claude_code",
                "default_model": "claude-default",
            },
        )
        project_id = project.json()["id"]
        session_local = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_local() as db:
            agent = AgentProfile(
                name="Legacy Codex reviewer",
                backend=AgentBackend.codex,
                model="legacy-codex-model",
                thinking_level="high",
                system_prompt="Review carefully.",
                config={},
            )
            db.add(agent)
            await db.commit()
            agent_id = str(agent.id)

        response = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "title": "Use portable agent",
                "initial_prompt": "Review this change",
                "agent_id": agent_id,
                "backend": "claude_code",
            },
        )

    assert response.status_code == 201
    assert response.json()["agent_id"] == agent_id
    assert response.json()["backend"] == "claude_code"
    assert response.json()["model"] == "claude-default"
    assert response.json()["thinking_level"] == "medium"


@pytest.mark.asyncio
async def test_delete_task_stops_active_run_and_removes_task(
    override_get_db, monkeypatch
):
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    cancel_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)
    monkeypatch.setattr(process_manager, "cancel", cancel_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await client.post(
            "/api/projects",
            json={"name": "Demo Project", "default_backend": "claude_code"},
        )
        task = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Delete me", "initial_prompt": "temporary task"},
        )
        task_id = task.json()["id"]

        response = await client.delete(f"/api/tasks/{task_id}")
        missing = await client.get(f"/api/tasks/{task_id}")

    assert response.status_code == 204
    cancel_mock.assert_awaited_once_with(uuid.UUID(task_id))
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_posting_a_message_persists_it_and_resumes_process_manager(
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

        resp = await client.get(f"/api/tasks/{task_id}")
        assert resp.json()["tags"] == ["Canvas"]

        # New tasks trigger once; follow-up messages use the atomic resume path.
        trigger_mock.assert_awaited_once()
        resume_mock.assert_awaited_once_with(uuid.UUID(task_id))

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


@pytest.mark.asyncio
async def test_switching_backend_uses_runtime_handoff_operation(override_get_db, monkeypatch):
    from app.db.models import AgentBackend
    from app.services.process_manager import process_manager

    trigger_mock = AsyncMock()
    switch_mock = AsyncMock()
    monkeypatch.setattr(process_manager, "trigger", trigger_mock)
    monkeypatch.setattr(process_manager, "switch_backend", switch_mock)

    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        project = await client.post(
            "/api/projects",
            json={"name": "Runtime project", "default_backend": "claude_code"},
        )
        task = await client.post(
            f"/api/projects/{project.json()['id']}/tasks",
            json={"title": "Switch me", "initial_prompt": "Continue this work"},
        )
        task_id = task.json()["id"]

        response = await client.patch(
            f"/api/tasks/{task_id}/backend", json={"backend": "codex"}
        )

    assert response.status_code == 200
    switch_mock.assert_awaited_once_with(uuid.UUID(task_id), AgentBackend.codex)
    assert trigger_mock.await_count == 1  # creation only; switch owns the replacement spawn
