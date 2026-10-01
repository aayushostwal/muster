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
    CapabilityImport,
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


@pytest.mark.asyncio
async def test_claude_uses_native_imported_mcp_without_duplicate_config(db_engine, tmp_path):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    source = tmp_path / "claude.json"
    source.write_text("{}")
    async with session_factory() as db:
        project = Project(name="Native MCP", default_backend=AgentBackend.claude_code)
        imported = GlobalMcpServer(name="jira", config={"transport": "stdio", "command": "jira-mcp"})
        manual = GlobalMcpServer(name="docs", config={"transport": "http", "url": "https://mcp.example.test"})
        db.add_all([project, imported, manual])
        await db.flush()
        db.add(CapabilityImport(
            resource_type="mcp", resource_id=imported.id, source_runtime="claude",
            source_scope="user", source_locator=f"{source}#mcpServers.jira",
            source_checksum="test",
        ))
        task = Task(project_id=project.id, title="Native MCP", initial_prompt="Search Jira", backend=AgentBackend.claude_code)
        db.add(task)
        await db.commit()
        loaded = await process_manager._load_project(db, project.id)
        assert loaded is not None
        claude_bindings = await process_manager._bindings_for(db, loaded, task)
        task.backend = AgentBackend.codex
        codex_bindings = await process_manager._bindings_for(db, loaded, task)

    assert "jira" not in claude_bindings.mcp_servers
    assert claude_bindings.native_claude_mcp_names == ("jira",)
    assert codex_bindings.native_claude_mcp_names == ()
    assert "docs" in claude_bindings.mcp_servers
    assert "jira" in codex_bindings.mcp_servers

    source.unlink()
    async with session_factory() as db:
        loaded = await process_manager._load_project(db, project.id)
        assert loaded is not None
        task.backend = AgentBackend.claude_code
        fallback_bindings = await process_manager._bindings_for(db, loaded, task)
    assert "jira" in fallback_bindings.mcp_servers
    assert fallback_bindings.native_claude_mcp_names == ()


@pytest.mark.asyncio
async def test_recurring_tool_denial_fails_without_creating_approval(db_engine, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from sqlalchemy import select
    from app.db.models import CronJob, Message, TaskInvocation
    from app.services.process_manager import ProcessManager, RunningProcess
    from app.services.agent_backends.base import PermissionRequest
    import app.services.process_manager as pm_module

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(pm_module, "SessionLocal", factory)
    monkeypatch.setattr(pm_module.settings, "data_dir", tmp_path)
    pm_module.settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pm_module, "broadcast", AsyncMock())
    manager = ProcessManager()
    terminate = AsyncMock()
    monkeypatch.setattr(manager, "_terminate_process_tree", terminate)
    async with factory() as db:
        project = Project(name="Unattended", default_backend=AgentBackend.claude_code)
        db.add(project)
        await db.flush()
        job = CronJob(project_id=project.id, name="triage", schedule_expr="0 * * * *", prompt="Check Slack", backend=AgentBackend.claude_code)
        db.add(job)
        await db.flush()
        task = Task(project_id=project.id, title="triage", initial_prompt="Check Slack", cron_job_id=job.id, status=TaskStatus.running, backend=AgentBackend.claude_code)
        db.add(task)
        await db.flush()
        invocation = TaskInvocation(task_id=task.id, sequence=1, backend=AgentBackend.claude_code, status="running")
        db.add(invocation)
        await db.commit()
        task_id, invocation_id = task.id, invocation.id
    process = SimpleNamespace(returncode=None)
    running = RunningProcess(process=process, invocation_id=invocation_id, backend=AgentBackend.claude_code)
    await manager._handle_permission_request(task_id, running, PermissionRequest(tool_name="mcp__jira__delete_issue", reason="Denied by project rule"))
    assert running.pending_final_status == TaskStatus.failed
    assert not running.blocking_question_hit
    terminate.assert_awaited_once_with(process)
    async with factory() as db:
        task = await db.get(Task, task_id)
        assert task.status == TaskStatus.failed and task.completed_at is not None
        assert (await db.execute(select(ToolApprovalRequest))).scalars().all() == []
        message = (await db.execute(select(Message))).scalar_one()
        assert not message.is_blocking_question
        assert "Denied by project rule" in message.content_text
