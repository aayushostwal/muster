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

        primary_update = await client.patch(
            f"/api/projects/{project_id}",
            json={"primary_directory_id": directory["id"]},
        )
        assert primary_update.status_code == 200
        assert primary_update.json()["primary_directory_id"] == directory["id"]
        assert (
            await client.delete(
                f"/api/projects/{project_id}/directories/{binding_response.json()['id']}"
            )
        ).status_code == 409

        created_with_root = await client.post(
            "/api/projects",
            json={
                "name": "Rooted project",
                "default_backend": "claude_code",
                "primary_directory_id": directory["id"],
            },
        )
        assert created_with_root.status_code == 201
        rooted_id = created_with_root.json()["id"]
        rooted_directories = await client.get(f"/api/projects/{rooted_id}/directories")
        assert rooted_directories.json()["items"][0]["directory_id"] == directory["id"]

        agent_response = await client.post(
            "/api/agents",
            json={
                "name": "Reviewer",
                "system_prompt": "Review changes for correctness.",
            },
        )
        assert agent_response.status_code == 201
        agent = agent_response.json()
        assert "backend" not in agent
        assert "model" not in agent
        assert "thinking_level" not in agent

        skill_response = await client.post(
            "/api/skills",
            json={
                "name": "Release",
                "instructions": "Validate the rollout.",
                "tags": [" Deployment ", "deployment", "Safety"],
            },
        )
        assert skill_response.status_code == 201
        skill = skill_response.json()
        assert skill["tags"] == ["Deployment", "Safety"]
        updated_skill = await client.patch(
            f"/api/skills/{skill['id']}", json={"tags": ["release"]}
        )
        assert updated_skill.json()["tags"] == ["release"]
        invalid_skill = await client.post(
            "/api/skills",
            json={"name": "Invalid", "instructions": "x", "tags": ["x" * 33]},
        )
        assert invalid_skill.status_code == 422

        tool_response = await client.post(
            "/api/global-tools",
            json={
                "name": "Workspace search",
                "description": "Search source safely",
                "config": {
                    "backend": "all",
                    "decision": "allow",
                    "claude_pattern": "Grep",
                    "codex_prefix": ["rg"],
                },
            },
        )
        assert tool_response.status_code == 201
        tool = tool_response.json()
        assert tool["enabled"] is True

        tool_capabilities = await client.get(
            f"/api/projects/{project_id}/capabilities/tool"
        )
        assert tool_capabilities.status_code == 200
        assert tool_capabilities.json()["items"][0]["name"] == "Workspace search"
        tool_override = await client.put(
            f"/api/projects/{project_id}/capabilities/tool/{tool['id']}",
            json={"enabled": False, "config_override": {}},
        )
        assert tool_override.status_code == 200
        assert tool_override.json()["enabled"] is False

        updated_tool = await client.patch(
            f"/api/global-tools/{tool['id']}",
            json={"description": "Search approved workspace roots"},
        )
        assert updated_tool.status_code == 200
        assert updated_tool.json()["description"] == "Search approved workspace roots"

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
        assert (await client.delete(f"/api/skills/{skill['id']}")).status_code == 204
        assert (await client.delete(f"/api/global-tools/{tool['id']}")).status_code == 204


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
