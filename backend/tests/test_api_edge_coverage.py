"""Additional API paths that protect validation, filtering, and metadata behavior."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import projects, registry, tasks
from app.db.models import AgentBackend, ContextSnapshot, Project, Task, TaskStatus
from app.db.session import get_db
from app.services import context_compression


def _app(override_get_db, *routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_task_query_update_history_and_transcript_paths(
    override_get_db, db_engine, monkeypatch, tmp_path
):
    manager = tasks.process_manager
    for name in ("trigger", "cancel", "complete", "restart_from_beginning", "retry_now", "switch_backend", "resume"):
        monkeypatch.setattr(manager, name, AsyncMock())

    app = _app(override_get_db, projects.router, tasks.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        assert (await client.get(f"/api/projects/{missing}/tasks")).status_code == 404
        project = (await client.post("/api/projects", json={"name": "P", "default_backend": "codex"})).json()
        project_id = project["id"]
        assert (await client.post(f"/api/projects/{project_id}/tasks", json={
            "title": "bad agent", "initial_prompt": "go", "agent_id": missing,
        })).status_code == 404
        assert (await client.post(f"/api/projects/{project_id}/tasks", json={
            "title": "terminal", "initial_prompt": "go", "runtime_mode": "interactive",
        })).status_code == 422

        created = await client.post(f"/api/projects/{project_id}/tasks", json={
            "title": "Task", "initial_prompt": "go", "backend": "codex", "tags": ["Bug"],
        })
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert len((await client.get(f"/api/projects/{project_id}/tasks?status=queued")).json()["items"]) == 1
        assert len((await client.get("/api/tasks?status=queued&status=running")).json()["items"]) == 1
        assert (await client.get(f"/api/tasks/{task_id}")).status_code == 200
        assert (await client.get(f"/api/tasks/{missing}")).status_code == 404

        assert (await client.patch(f"/api/tasks/{task_id}/model", json={"model": "gpt"})).json()["model"] == "gpt"
        assert (await client.patch(f"/api/tasks/{task_id}/models", json={"models": []})).status_code == 422
        models = await client.patch(f"/api/tasks/{task_id}/models", json={"models": ["one", "two"]})
        assert models.json()["fallback_models"] == ["two"]
        assert (await client.patch(f"/api/tasks/{task_id}/thinking-level", json={"thinking_level": "invalid"})).status_code == 422
        assert (await client.patch(f"/api/tasks/{task_id}/thinking-level", json={"thinking_level": "high"})).json()["thinking_level"] == "high"
        assert (await client.patch(f"/api/tasks/{task_id}/context-strategy", json={"context_strategy": "summary"})).json()["context_strategy"] == "summary"
        assert (await client.patch(f"/api/tasks/{task_id}/backend", json={"backend": "claude_code"})).status_code == 200
        assert (await client.post(f"/api/tasks/{task_id}/retry-now")).status_code == 200

        assert (await client.get(f"/api/tasks/{task_id}/run-attempts")).json() == {"items": []}
        assert (await client.get(f"/api/tasks/{task_id}/invocations")).json() == {"items": []}
        assert (await client.get(f"/api/tasks/{task_id}/events")).json() == {"items": []}
        assert (await client.get(f"/api/tasks/{task_id}/transcript")).status_code == 404

        transcript = tmp_path / "task.jsonl"
        transcript.write_text('{"text":"hello"}\n')
        session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_factory() as db:
            db.add(ContextSnapshot(task_id=uuid.UUID(task_id), summary_text="S", raw_transcript_path=str(transcript)))
            await db.commit()
        response = await client.get(f"/api/tasks/{task_id}/transcript")
        assert response.json()["transcript"] == '{"text":"hello"}\n'
        transcript.unlink()
        assert (await client.get(f"/api/tasks/{task_id}/transcript")).status_code == 404

        monkeypatch.setattr(context_compression, "compress", AsyncMock())
        compressed = await client.post(f"/api/tasks/{task_id}/compress-context")
        assert compressed.status_code == 200


@pytest.mark.asyncio
async def test_task_compress_requires_snapshot(override_get_db, monkeypatch):
    monkeypatch.setattr(tasks.process_manager, "trigger", AsyncMock())
    monkeypatch.setattr(context_compression, "compress", AsyncMock())
    app = _app(override_get_db, projects.router, tasks.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id = (await client.post("/api/projects", json={"name": "P", "default_backend": "codex"})).json()["id"]
        task_id = (await client.post(f"/api/projects/{project_id}/tasks", json={"title": "T", "initial_prompt": "go"})).json()["id"]
        assert (await client.post(f"/api/tasks/{task_id}/compress-context")).status_code == 500


@pytest.mark.asyncio
async def test_registry_full_crud_errors_and_capability_overrides(override_get_db, monkeypatch):
    app = _app(override_get_db, projects.router, registry.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        project_id = (await client.post("/api/projects", json={"name": "P", "default_backend": "codex"})).json()["id"]

        directory = (await client.post("/api/directories", json={"name": "D", "path": "/d"})).json()
        assert len((await client.get("/api/directories")).json()["items"]) == 1
        assert (await client.patch(f"/api/directories/{directory['id']}", json={"description": "updated"})).json()["description"] == "updated"
        assert (await client.patch(f"/api/directories/{missing}", json={"description": "x"})).status_code == 404

        mcp = (await client.post("/api/mcp-servers", json={
            "name": "M", "config": {"transport": "stdio", "command": "serve"},
        })).json()
        assert len((await client.get("/api/mcp-servers")).json()["items"]) == 1
        mcp = (await client.patch(f"/api/mcp-servers/{mcp['id']}", json={
            "config": {"transport": "http", "url": "https://mcp.test"},
        })).json()
        assert mcp["config"]["transport"] == "http"
        assert (await client.patch(f"/api/mcp-servers/{missing}", json={"name": "x"})).status_code == 404

        skill = (await client.post("/api/skills", json={"name": "Review", "instructions": "Review code"})).json()
        assert len((await client.get("/api/skills")).json()["items"]) == 1
        assert (await client.patch(f"/api/skills/{skill['id']}", json={"description": "D"})).json()["description"] == "D"
        assert (await client.patch(f"/api/skills/{missing}", json={"description": "x"})).status_code == 404

        tool = (await client.post("/api/global-tools", json={
            "name": "Search", "config": {"backend": "codex", "decision": "allow", "codex_prefix": ["rg"]},
        })).json()
        assert len((await client.get("/api/global-tools")).json()["items"]) == 1
        tool = (await client.patch(f"/api/global-tools/{tool['id']}", json={
            "config": {"backend": "codex", "decision": "deny", "codex_prefix": ["rg"]},
        })).json()
        assert tool["config"]["decision"] == "deny"

        assert (await client.get(f"/api/projects/{missing}/capabilities/tool")).status_code == 404
        assert (await client.get(f"/api/projects/{project_id}/capabilities/unknown")).status_code == 422
        assert (await client.put(f"/api/projects/{project_id}/capabilities/unknown/{missing}", json={"enabled": True})).status_code == 422
        assert (await client.put(f"/api/projects/{missing}/capabilities/tool/{tool['id']}", json={"enabled": True})).status_code == 404
        assert (await client.put(f"/api/projects/{project_id}/capabilities/tool/{missing}", json={"enabled": True})).status_code == 404
        first = await client.put(f"/api/projects/{project_id}/capabilities/tool/{tool['id']}", json={
            "enabled": False, "config_override": {"extra": True},
        })
        second = await client.put(f"/api/projects/{project_id}/capabilities/tool/{tool['id']}", json={
            "enabled": True, "config_override": {},
        })
        assert first.status_code == second.status_code == 200

        catalog = {"backend": "codex", "items": [], "refreshed_at": "2025-01-01T00:00:00Z", "expires_at": "2025-01-01T01:00:00Z", "cached": False, "discovery_error": None}
        monkeypatch.setattr(registry, "get_catalog", AsyncMock(return_value=catalog))
        assert (await client.get("/api/models/codex?refresh=true")).status_code == 200

        assert (await client.delete(f"/api/mcp-servers/{mcp['id']}")).status_code == 204
        assert (await client.delete(f"/api/skills/{skill['id']}")).status_code == 204
        assert (await client.delete(f"/api/global-tools/{tool['id']}")).status_code == 204
        assert (await client.delete(f"/api/directories/{directory['id']}")).status_code == 204
