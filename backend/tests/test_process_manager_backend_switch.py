"""Cross-runtime task handoff lifecycle tests."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AgentBackend,
    AgentProfile,
    Message,
    MessageSender,
    Project,
    Task,
    TaskStatus,
    ToolApprovalRequest,
)
from app.services import process_manager as process_manager_module
from app.services.process_manager import ProcessManager


@pytest.mark.asyncio
async def test_switch_backend_starts_fresh_session_with_conversation_handoff(
    db_engine, monkeypatch
):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)
    monkeypatch.setattr(process_manager_module, "broadcast", AsyncMock())

    now = datetime.now(timezone.utc)
    async with session_local() as db:
        project = Project(name="Runtime switch", default_backend=AgentBackend.claude_code)
        agent = AgentProfile(
            name="Portable reviewer",
            system_prompt="Review carefully.",
            config={},
        )
        db.add_all([project, agent])
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Continue elsewhere",
            initial_prompt="Implement the original feature.",
            status=TaskStatus.done,
            attention_reason="awaiting_review",
            backend=AgentBackend.claude_code,
            agent_id=agent.id,
            model="claude-sonnet",
            fallback_models=["claude-haiku"],
            session_id="claude-native-session",
            started_at=now,
            completed_at=now,
        )
        db.add(task)
        await db.flush()
        db.add_all(
            [
                Message(
                    task_id=task.id,
                    sender=MessageSender.user,
                    content_text="Keep the API backwards compatible.",
                    media=[
                        {
                            "kind": "magic_canvas",
                            "title": "API plan",
                            "format": "markdown",
                            "content": "# Current contract",
                        }
                    ],
                ),
                Message(
                    task_id=task.id,
                    sender=MessageSender.agent,
                    content_text="The backend endpoint is implemented.",
                ),
                ToolApprovalRequest(
                    task_id=task.id,
                    backend=AgentBackend.claude_code,
                    tool_name="Bash",
                    tool_input={"command": "git status"},
                    permission_rule={},
                    status="pending",
                ),
            ]
        )
        await db.commit()
        task_id = task.id
        agent_id = agent.id

    manager = ProcessManager()
    spawn = AsyncMock()
    append_transcript = AsyncMock()
    monkeypatch.setattr(manager, "_spawn", spawn)
    monkeypatch.setattr(manager, "_append_transcript", append_transcript)

    await manager.switch_backend(task_id, AgentBackend.codex)

    async with session_local() as db:
        switched = await db.get(Task, task_id)
        messages = (
            await db.execute(select(Message).where(Message.task_id == task_id))
        ).scalars().all()
        approval = (
            await db.execute(
                select(ToolApprovalRequest).where(ToolApprovalRequest.task_id == task_id)
            )
        ).scalar_one()

    assert switched is not None
    assert switched.backend == AgentBackend.codex
    assert switched.agent_id == agent_id
    assert switched.status == TaskStatus.queued
    assert switched.attention_reason is None
    assert switched.session_id is None
    assert switched.model is None
    assert switched.fallback_models == []
    assert switched.started_at is not None
    assert switched.completed_at is None
    assert approval.status == "superseded"
    assert approval.resolution_scope == "runtime_switch"
    assert "Runtime switched from Claude Code to Codex" in (messages[-1].content_text or "")

    spawn.assert_awaited_once()
    assert spawn.await_args.args == (task_id,)
    handoff = spawn.await_args.kwargs["initial_prompt"]
    assert "ORIGINAL BRIEF\nImplement the original feature." in handoff
    assert "[USER]\nKeep the API backwards compatible." in handoff
    assert "<magic_canvas_snapshots>" in handoff
    assert "# Current contract" in handoff
    assert "[CLAUDE CODE]\nThe backend endpoint is implemented." in handoff
    append_transcript.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_backend_is_noop_when_runtime_is_unchanged(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)

    async with session_local() as db:
        project = Project(name="Same runtime", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="No switch",
            initial_prompt="Stay here.",
            status=TaskStatus.done,
            backend=AgentBackend.codex,
            session_id="codex-session",
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    manager = ProcessManager()
    spawn = AsyncMock()
    pending_retry = Mock()
    manager._pending_retries[task_id] = pending_retry
    monkeypatch.setattr(manager, "_spawn", spawn)

    await manager.switch_backend(task_id, AgentBackend.codex)

    async with session_local() as db:
        unchanged = await db.get(Task, task_id)
    assert unchanged is not None
    assert unchanged.session_id == "codex-session"
    assert manager._pending_retries[task_id] is pending_retry
    pending_retry.cancel.assert_not_called()
    spawn.assert_not_awaited()
