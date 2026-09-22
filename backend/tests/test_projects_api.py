"""Tests for the full /api/projects CRUD lifecycle."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import projects
from app.db.session import get_db


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_project_crud_lifecycle(override_get_db):
    app = _build_app(override_get_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # create
        resp = await client.post(
            "/api/projects",
            json={
                "name": "Demo Project",
                "description": "a test project",
                "default_backend": "claude_code",
            },
        )
        assert resp.status_code == 201
        project = resp.json()
        project_id = project["id"]
        assert project["name"] == "Demo Project"
        assert project["default_context_strategy"] == "full"

        # list
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == project_id

        # get
        resp = await client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Demo Project"

        # get missing -> 404
        resp = await client.get(f"/api/projects/{uuid.uuid4()}")
        assert resp.status_code == 404

        # partial update
        resp = await client.patch(f"/api/projects/{project_id}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"
        assert resp.json()["description"] == "a test project"  # untouched

        # delete
        resp = await client.delete(f"/api/projects/{project_id}")
        assert resp.status_code == 204
        resp = await client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 404
