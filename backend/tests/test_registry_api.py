"""Integration coverage for global resources and project capability overrides."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import directories, projects, registry
from app.db.session import get_db


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(registry.router, prefix="/api")
    app.include_router(directories.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_global_registry_and_project_access(override_get_db):
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_response = await client.post(
            "/api/projects",
            json={"name": "Runtime", "default_backend": "codex"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        directory_response = await client.post(
            "/api/directories",
            json={"name": "Repository", "path": "/workspace/repository"},
        )
        assert directory_response.status_code == 201
        directory = directory_response.json()
        assert (await client.post("/api/directories", json={"name": "Relative", "path": "tmp"})).status_code == 422

        binding_response = await client.post(
            f"/api/projects/{project_id}/directories",
            json={"directory_id": directory["id"], "access_scope": "read_write"},
        )
        assert binding_response.status_code == 201
        assert binding_response.json()["name"] == "Repository"
        duplicate = await client.post(
            f"/api/projects/{project_id}/directories",
            json={"directory_id": directory["id"], "access_scope": "read"},
        )
        assert duplicate.status_code == 409

        agent_response = await client.post(
            "/api/agents",
            json={
                "name": "Reviewer",
                "backend": "codex",
                "system_prompt": "Review changes for correctness.",
                "thinking_level": "high",
            },
        )
        assert agent_response.status_code == 201
        agent = agent_response.json()

        capabilities = await client.get(f"/api/projects/{project_id}/capabilities/agent")
        assert capabilities.status_code == 200
        assert capabilities.json()["items"][0]["enabled"] is True

        override = await client.put(
            f"/api/projects/{project_id}/capabilities/agent/{agent['id']}",
            json={"enabled": False, "config_override": {}},
        )
        assert override.status_code == 200
        assert override.json()["enabled"] is False
        capabilities = await client.get(f"/api/projects/{project_id}/capabilities/agent")
        assert capabilities.json()["items"][0]["enabled"] is False

        updated = await client.patch(
            f"/api/agents/{agent['id']}",
            json={"description": "Production review agent"},
        )
        assert updated.status_code == 200
        assert updated.json()["description"] == "Production review agent"
        assert (await client.delete(f"/api/agents/{agent['id']}")).status_code == 204


@pytest.mark.asyncio
async def test_registry_rejects_duplicate_names(override_get_db):
    app = _build_app(override_get_db)
    payload = {
        "name": "Filesystem",
        "config": {"command": "npx", "args": ["-y", "server"], "env": {}},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/mcp-servers", json=payload)).status_code == 201
        duplicate = await client.post("/api/mcp-servers", json=payload)
        assert duplicate.status_code == 409
