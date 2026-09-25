"""CRUD and error-path coverage for project-scoped resources."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import artifacts, cron, directories, mcp_servers, projects, registry, secrets, tools
from app.db.session import get_db


def _app(override_get_db) -> FastAPI:
    app = FastAPI()
    for router in (
        projects.router,
        registry.router,
        directories.router,
        artifacts.router,
        secrets.router,
        mcp_servers.router,
        tools.router,
        cron.router,
    ):
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


async def _project(client: AsyncClient) -> str:
    response = await client.post("/api/projects", json={"name": "Coverage", "default_backend": "codex"})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_artifact_crud_and_not_found_paths(override_get_db):
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        assert (await client.get(f"/api/projects/{missing}/artifacts")).status_code == 404
        assert (await client.post(f"/api/projects/{missing}/artifacts", json={"name": "A", "local_path": "/a"})).status_code == 404

        project_id = await _project(client)
        created = await client.post(
            f"/api/projects/{project_id}/artifacts",
            json={"name": "report", "local_path": "/tmp/report", "remote_url": "https://example.test/report"},
        )
        assert created.status_code == 201
        artifact = created.json()
        assert (await client.get(f"/api/projects/{project_id}/artifacts")).json()["items"] == [artifact]
        assert (await client.delete(f"/api/projects/{project_id}/artifacts/{uuid.uuid4()}")).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/artifacts/{artifact['id']}")).status_code == 204


@pytest.mark.asyncio
async def test_secret_crud_never_returns_values(override_get_db, monkeypatch):
    monkeypatch.setattr(secrets, "encrypt_secret", lambda value: f"encrypted:{value}".encode())
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        assert (await client.get(f"/api/projects/{missing}/secrets")).status_code == 404
        assert (await client.put(f"/api/projects/{missing}/secrets/key", json={"value": "one"})).status_code == 404
        project_id = await _project(client)
        first = await client.put(f"/api/projects/{project_id}/secrets/key", json={"value": "one"})
        second = await client.put(f"/api/projects/{project_id}/secrets/key", json={"value": "two"})
        assert first.status_code == second.status_code == 200
        assert "value" not in second.json()
        assert len((await client.get(f"/api/projects/{project_id}/secrets")).json()["items"]) == 1
        assert (await client.delete(f"/api/projects/{project_id}/secrets/missing")).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/secrets/key")).status_code == 204


@pytest.mark.asyncio
async def test_mcp_binding_crud_and_validation(override_get_db):
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        stdio = {"transport": "stdio", "command": "server", "args": [], "env": {}}
        assert (await client.get(f"/api/projects/{missing}/mcp-servers")).status_code == 404
        assert (await client.post(f"/api/projects/{missing}/mcp-servers", json={"name": "m", "config": stdio})).status_code == 404
        assert (await client.post(f"/api/projects/{missing}/mcp-servers", json={"name": "m", "config": {"transport": "stdio"}})).status_code == 422
        assert (await client.post(f"/api/projects/{missing}/mcp-servers", json={"name": "m", "config": {"transport": "http"}})).status_code == 422

        project_id = await _project(client)
        created = await client.post(f"/api/projects/{project_id}/mcp-servers", json={"name": "m", "config": stdio})
        binding_id = created.json()["id"]
        assert len((await client.get(f"/api/projects/{project_id}/mcp-servers")).json()["items"]) == 1
        updated = await client.patch(
            f"/api/projects/{project_id}/mcp-servers/{binding_id}",
            json={"name": "remote", "config": {"transport": "http", "url": "https://mcp.test"}},
        )
        assert updated.json()["config"]["transport"] == "http"
        bad_id = uuid.uuid4()
        assert (await client.patch(f"/api/projects/{project_id}/mcp-servers/{bad_id}", json={"name": "x"})).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/mcp-servers/{bad_id}")).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/mcp-servers/{binding_id}")).status_code == 204


@pytest.mark.asyncio
async def test_tool_binding_crud_duplicates_and_validation(override_get_db):
    config = {"backend": "all", "decision": "allow", "claude_pattern": "Read", "codex_prefix": ["cat"]}
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        assert (await client.get(f"/api/projects/{missing}/tools")).status_code == 404
        assert (await client.post(f"/api/projects/{missing}/tools", json={"name": "rule", "config": config})).status_code == 404
        assert (await client.post(f"/api/projects/{missing}/tools", json={"name": "rule", "config": {"backend": "all"}})).status_code == 422
        project_id = await _project(client)
        created = await client.post(f"/api/projects/{project_id}/tools", json={"name": "rule", "config": config})
        binding_id = created.json()["id"]
        assert len((await client.get(f"/api/projects/{project_id}/tools")).json()["items"]) == 1
        assert (await client.post(f"/api/projects/{project_id}/tools", json={"name": "rule", "config": config})).status_code == 409
        assert (await client.delete(f"/api/projects/{project_id}/tools/{uuid.uuid4()}")).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/tools/{binding_id}")).status_code == 204


@pytest.mark.asyncio
async def test_cron_crud_syncs_scheduler(override_get_db, monkeypatch):
    sync = monkeypatch.setattr(cron, "sync_jobs_from_db", lambda: None)
    del sync
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        assert (await client.get(f"/api/projects/{missing}/cron-jobs")).status_code == 404
        project_id = await _project(client)
        created = await client.post(
            f"/api/projects/{project_id}/cron-jobs",
            json={"name": "daily", "schedule_expr": "0 9 * * *", "prompt": "report", "backend": "codex"},
        )
        assert created.status_code == 201
        cron_id = created.json()["id"]
        assert len((await client.get(f"/api/projects/{project_id}/cron-jobs")).json()["items"]) == 1
        assert (await client.patch(f"/api/projects/{project_id}/cron-jobs/{cron_id}", json={"name": "weekday"})).json()["name"] == "weekday"
        assert (await client.post(f"/api/projects/{project_id}/cron-jobs/{cron_id}/disable")).json()["enabled"] is False
        assert (await client.post(f"/api/projects/{project_id}/cron-jobs/{cron_id}/enable")).json()["enabled"] is True
        bad = uuid.uuid4()
        for method, suffix in (("patch", ""), ("post", "/enable"), ("post", "/disable"), ("delete", "")):
            response = await getattr(client, method)(f"/api/projects/{project_id}/cron-jobs/{bad}{suffix}", **({"json": {}} if method == "patch" else {}))
            assert response.status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/cron-jobs/{cron_id}")).status_code == 204


@pytest.mark.asyncio
async def test_directory_success_and_error_paths(override_get_db):
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        project_id = await _project(client)
        missing = str(uuid.uuid4())
        assert (await client.post(f"/api/projects/{project_id}/directories", json={"directory_id": missing, "access_scope": "read"})).status_code == 404
        assert (await client.get(f"/api/projects/{missing}/directories")).status_code == 404
        directory = (await client.post("/api/directories", json={"name": "Read", "path": "/read"})).json()
        binding = await client.post(
            f"/api/projects/{project_id}/directories",
            json={"directory_id": directory["id"], "access_scope": "read"},
        )
        assert binding.status_code == 201
        assert (await client.patch(f"/api/projects/{project_id}", json={"primary_directory_id": directory["id"]})).status_code == 422
        assert (await client.delete(f"/api/projects/{project_id}/directories/{uuid.uuid4()}")).status_code == 404
        assert (await client.delete(f"/api/projects/{project_id}/directories/{binding.json()['id']}")).status_code == 204


@pytest.mark.asyncio
async def test_project_primary_directory_error_paths(override_get_db):
    async with AsyncClient(transport=ASGITransport(app=_app(override_get_db)), base_url="http://test") as client:
        missing = str(uuid.uuid4())
        response = await client.post(
            "/api/projects",
            json={"name": "Bad root", "default_backend": "codex", "primary_directory_id": missing},
        )
        assert response.status_code == 404
        project_id = await _project(client)
        assert (await client.patch(f"/api/projects/{project_id}", json={"primary_directory_id": missing})).status_code == 422
