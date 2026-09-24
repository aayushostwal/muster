"""Restart-from-beginning lifecycle tests."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AgentBackend,
    Message,
    MessageSender,
    Project,
    Task,
    TaskInvocation,
    TaskStatus,
    ToolApprovalRequest,
)
from app.services import process_manager as process_manager_module
from app.services.process_manager import ProcessManager, RunningProcess


@pytest.mark.asyncio
async def test_restart_clears_resume_state_preserves_history_and_supersedes_approvals(
    db_engine, monkeypatch
):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)
    monkeypatch.setattr(process_manager_module, "broadcast", AsyncMock())

    now = datetime.now(timezone.utc)
    async with session_local() as db:
        project = Project(name="Restart project", default_backend=AgentBackend.claude_code)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Restart me",
            initial_prompt="This must be the first prompt in the new session.",
            status=TaskStatus.done,
            backend=AgentBackend.claude_code,
            session_id="old-native-session",
            started_at=now,
            completed_at=now,
        )
        db.add(task)
        await db.flush()
        db.add(Message(task_id=task.id, sender=MessageSender.user, content_text="keep me"))
        db.add(
            ToolApprovalRequest(
                task_id=task.id,
                backend=AgentBackend.claude_code,
                tool_name="Bash",
                tool_input={"command": "git status"},
                permission_rule={},
                status="pending",
            )
        )
        await db.commit()
        task_id = task.id

    manager = ProcessManager()
    spawn = AsyncMock()
    append_transcript = AsyncMock()
    monkeypatch.setattr(manager, "_spawn", spawn)
    monkeypatch.setattr(manager, "_append_transcript", append_transcript)

    await manager.restart_from_beginning(task_id)

    async with session_local() as db:
        restarted = await db.get(Task, task_id)
        messages = (
            await db.execute(select(Message).where(Message.task_id == task_id))
        ).scalars().all()
        approval = (
            await db.execute(
                select(ToolApprovalRequest).where(ToolApprovalRequest.task_id == task_id)
            )
        ).scalar_one()

    assert restarted is not None
    assert restarted.status == TaskStatus.queued
    assert restarted.session_id is None
    assert restarted.started_at is None
    assert restarted.completed_at is None
    assert [message.content_text for message in messages] == [
        "keep me",
        "Restarted from the beginning in a new agent session. The original brief is being sent again.",
    ]
    assert approval.status == "superseded"
    assert approval.resolution_scope == "restart"
    assert approval.resolved_at is not None
    spawn.assert_awaited_once_with(task_id)
    append_transcript.assert_awaited_once()


@pytest.mark.asyncio
async def test_restarted_invocation_exit_does_not_cancel_or_complete_task(
    db_engine, monkeypatch
):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)
    monkeypatch.setattr(process_manager_module, "broadcast", AsyncMock())

    async with session_local() as db:
        project = Project(name="Active project", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Active task",
            initial_prompt="Start here",
            status=TaskStatus.running,
            backend=AgentBackend.codex,
        )
        db.add(task)
        await db.flush()
        invocation = TaskInvocation(
            task_id=task.id,
            sequence=1,
            backend=AgentBackend.codex,
            status="running",
        )
        db.add(invocation)
        await db.commit()
        task_id = task.id
        invocation_id = invocation.id

    class ExitedProcess:
        returncode = -15

        async def wait(self):
            return self.returncode

    manager = ProcessManager()
    set_status = AsyncMock()
    monkeypatch.setattr(manager, "_set_status", set_status)
    running = RunningProcess(
        process=ExitedProcess(),  # type: ignore[arg-type]
        invocation_id=invocation_id,
        backend=AgentBackend.codex,
        restart_requested=True,
    )
    manager._running[task_id] = running

    await manager._on_process_exit(task_id, running.process, running)  # type: ignore[arg-type]

    async with session_local() as db:
        stopped_invocation = await db.get(TaskInvocation, invocation_id)
    assert stopped_invocation is not None
    assert stopped_invocation.status == "cancelled"
    assert task_id not in manager._running
    set_status.assert_not_awaited()
