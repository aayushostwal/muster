"""Integration coverage for project tool rules and interactive approvals."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import projects, tools
from app.db.models import (
    AgentBackend,
    AgentProfile,
    GlobalMcpServer,
    GlobalTool,
    Project,
    ProjectCapabilityOverride,
    Skill,
    Task,
    TaskStatus,
    ToolApprovalRequest,
)
from app.db.session import get_db
from app.services.process_manager import process_manager


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


@pytest.mark.asyncio
async def test_global_tool_rules_are_inherited_and_can_be_disabled(db_engine):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        project = Project(name="Runtime", default_backend=AgentBackend.codex)
        global_tool = GlobalTool(
            name="Workspace search",
            config={
                "backend": "all",
                "decision": "allow",
                "claude_pattern": "Grep",
                "codex_prefix": ["rg"],
            },
        )
        db.add_all([project, global_tool])
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Search",
            initial_prompt="Find references",
            backend=AgentBackend.codex,
        )
        db.add(task)
        await db.commit()

        loaded = await process_manager._load_project(db, project.id)
        assert loaded is not None
        bindings = await process_manager._bindings_for(db, loaded, task)
        assert bindings.tool_rules == [global_tool.config]

        db.add(
            ProjectCapabilityOverride(
                project_id=project.id,
                resource_type="tool",
                resource_id=global_tool.id,
                enabled=False,
                config_override={},
            )
        )
        await db.commit()
        bindings = await process_manager._bindings_for(db, loaded, task)
    assert bindings.tool_rules == []


@pytest.mark.asyncio
async def test_agents_skills_and_mcp_are_portable_across_runtimes(db_engine):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_local() as db:
        project = Project(name="Portable", default_backend=AgentBackend.claude_code)
        agent = AgentProfile(
            name="Reviewer",
            description="Reviews changes",
            backend=AgentBackend.codex,  # legacy value must not scope the profile
            system_prompt="Review carefully.",
            config={},
        )
        skill = Skill(
            name="Release",
            instructions="Validate rollback.",
            tags=["deployment"],
        )
        connector = GlobalMcpServer(
            name="docs",
            config={"transport": "http", "url": "https://mcp.example.test"},
        )
        db.add_all([project, agent, skill, connector])
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Portable task",
            initial_prompt="/Reviewer /Release check this",
            backend=AgentBackend.claude_code,
            agent_id=agent.id,
        )
        db.add(task)
        await db.commit()

        loaded = await process_manager._load_project(db, project.id)
        assert loaded is not None
        claude_bindings = await process_manager._bindings_for(db, loaded, task)
        task.backend = AgentBackend.codex
        codex_bindings = await process_manager._bindings_for(db, loaded, task)

    for bindings in (claude_bindings, codex_bindings):
        assert bindings.selected_agent_prompt == "Review carefully."
        assert bindings.agent_profiles["Reviewer"]["prompt"] == "Review carefully."
        assert bindings.skills == {"Release": "Validate rollback."}
        assert bindings.mcp_servers["docs"]["url"] == "https://mcp.example.test"
