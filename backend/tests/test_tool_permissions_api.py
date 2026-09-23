"""Integration coverage for project tool rules and interactive approvals."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import projects, tools
from app.db.models import AgentBackend, Task, TaskStatus, ToolApprovalRequest
from app.db.session import get_db


@pytest.mark.asyncio
async def test_project_tool_rules_and_always_allow_resolution(
    override_get_db, db_engine, monkeypatch
):
    app = FastAPI()
    app.include_router(projects.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(tools.task_router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    resume = AsyncMock()
    monkeypatch.setattr(tools.process_manager, "resume_after_approval", resume)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project = (
            await client.post(
                "/api/projects", json={"name": "Runtime", "default_backend": "claude_code"}
            )
        ).json()
        rule = {
            "name": "Git operations",
            "config": {
                "backend": "all",
                "decision": "allow",
                "claude_pattern": "Bash(git *)",
                "codex_prefix": ["git"],
            },
        }
        created_rule = await client.post(f"/api/projects/{project['id']}/tools", json=rule)
        assert created_rule.status_code == 201
        assert created_rule.json()["config"]["codex_prefix"] == ["git"]

        session_local = async_sessionmaker(db_engine, expire_on_commit=False)
        async with session_local() as db:
            task = Task(
                project_id=UUID(project["id"]),
                title="Open a PR",
                initial_prompt="Open a PR",
                status=TaskStatus.waiting_on_you,
                backend=AgentBackend.claude_code,
            )
            db.add(task)
            await db.flush()
            approval = ToolApprovalRequest(
                task_id=task.id,
                backend=AgentBackend.claude_code,
                tool_name="Bash",
                tool_input={"command": "gh pr create"},
                permission_rule={
                    "backend": "claude_code",
                    "decision": "allow",
                    "claude_pattern": "Bash(gh *)",
                    "codex_prefix": [],
                },
            )
            db.add(approval)
            await db.commit()
            approval_id = str(approval.id)
            task_id = str(task.id)

        response = await client.post(
            f"/api/tasks/{task_id}/tool-approvals/{approval_id}/resolve",
            json={"decision": "always_allow"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved_project"
        resume.assert_awaited_once()

        project_rules = await client.get(f"/api/projects/{project['id']}/tools")
        assert len(project_rules.json()["items"]) == 2
        assert any(
            item["config"].get("claude_pattern") == "Bash(gh *)"
            for item in project_rules.json()["items"]
        )
