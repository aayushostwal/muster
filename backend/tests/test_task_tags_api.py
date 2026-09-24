from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects, task_tags, tasks
from app.db.session import get_db


def _app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(task_tags.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_catalog_persists_presets_custom_tags_and_renames_assignments(
    override_get_db, monkeypatch
):
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    async with AsyncClient(
        transport=ASGITransport(app=_app(override_get_db)), base_url="http://test"
    ) as client:
        project = (
            await client.post(
                "/api/projects", json={"name": "Demo", "default_backend": "claude_code"}
            )
        ).json()
        project_id = project["id"]

        catalog = (await client.get(f"/api/projects/{project_id}/task-tags")).json()["items"]
        by_name = {item["name"]: item for item in catalog}
        assert {"PR Raised", "PR Reviewed", "Canvas", "Bug", "Feature"} <= set(by_name)
        assert by_name["PR Raised"]["kind"] == "system"

        custom = (
            await client.post(
                f"/api/projects/{project_id}/task-tags", json={"name": "Customer beta"}
            )
        ).json()
        task = (
            await client.post(
                f"/api/projects/{project_id}/tasks",
                json={
                    "title": "Beta",
                    "initial_prompt": "Prepare beta",
                    "tags": ["Customer beta"],
                },
            )
        ).json()

        renamed = await client.patch(
            f"/api/projects/{project_id}/task-tags/{custom['id']}",
            json={"name": "Customer preview"},
        )
        assert renamed.status_code == 200
        assert (await client.get(f"/api/tasks/{task['id']}")).json()["tags"] == [
            "Customer preview"
        ]

        system_rename = await client.patch(
            f"/api/projects/{project_id}/task-tags/{by_name['PR Raised']['id']}",
            json={"name": "Looks like a PR"},
        )
        assert system_rename.status_code == 422


@pytest.mark.asyncio
async def test_system_tags_cannot_be_assigned_at_task_creation(override_get_db, monkeypatch):
    from app.services.process_manager import process_manager

    monkeypatch.setattr(process_manager, "trigger", AsyncMock())
    async with AsyncClient(
        transport=ASGITransport(app=_app(override_get_db)), base_url="http://test"
    ) as client:
        project_id = (
            await client.post(
                "/api/projects", json={"name": "Demo", "default_backend": "claude_code"}
            )
        ).json()["id"]
        response = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "Fake", "initial_prompt": "Fake it", "tags": ["PR Raised"]},
        )
        assert response.status_code == 422

