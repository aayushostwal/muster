"""Regression coverage for interrupted and unresponsive agent runtimes."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.models import (
    AgentBackend,
    Message,
    MessageSender,
    Project,
    Task,
    TaskInvocation,
    TaskStatus,
)
from app.services import process_manager as process_manager_module
from app.services.context_compression import _summarize_command
from app.services.process_manager import ProcessManager, RunningProcess


def test_codex_context_compression_uses_stdin_prompt():
    command = _summarize_command(AgentBackend.codex, "Summarize this")

    assert command.argv[1:] == ["exec", "-", "--json"]
    assert command.stdin_payload == "Summarize this"


@pytest.mark.asyncio
async def test_startup_reconciles_orphaned_running_rows(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)
    monkeypatch.setattr(ProcessManager, "_append_transcript", AsyncMock())

    async with session_local() as db:
        project = Project(name="Interrupted", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Orphaned task",
            initial_prompt="Keep working",
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

    reconciled = await ProcessManager().reconcile_interrupted_tasks()

    async with session_local() as db:
        task = await db.get(Task, task_id)
        invocation = await db.get(TaskInvocation, invocation_id)
        messages = (
            await db.execute(
                select(Message).where(
                    Message.task_id == task_id,
                    Message.sender == MessageSender.system,
                )
            )
        ).scalars().all()
    assert reconciled == 1
    assert task is not None and task.status == TaskStatus.waiting_on_you
    assert invocation is not None and invocation.status == "interrupted"
    assert invocation.completed_at is not None
    assert "restarted" in (messages[-1].content_text or "").lower()


@pytest.mark.asyncio
async def test_watchdog_terminates_runtime_without_structured_startup(monkeypatch):
    class HangingProcess:
        returncode = None

        def terminate(self):
            self.returncode = -15

        async def wait(self):
            return self.returncode

    monkeypatch.setattr(settings, "runtime_watchdog_interval_seconds", 0.001)
    monkeypatch.setattr(settings, "runtime_startup_timeout_seconds", 0)
    process = HangingProcess()
    running = RunningProcess(
        process=process,  # type: ignore[arg-type]
        invocation_id=uuid.uuid4(),
        backend=AgentBackend.codex,
    )

    await ProcessManager()._watchdog(uuid.uuid4(), running)

    assert process.returncode == -15
    assert running.failure_reason is not None
    assert "startup timed out" in running.failure_reason.lower()


@pytest.mark.asyncio
async def test_stdout_reader_failure_stops_runtime(monkeypatch):
    class BrokenStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ValueError("Separator is found, but chunk is longer than limit")

    class Process:
        stdout = BrokenStream()
        returncode = None

    manager = ProcessManager()
    terminate = AsyncMock()
    on_exit = AsyncMock()
    monkeypatch.setattr(manager, "_terminate_process_tree", terminate)
    monkeypatch.setattr(manager, "_on_process_exit", on_exit)
    process = Process()
    running = RunningProcess(
        process=process,  # type: ignore[arg-type]
        invocation_id=uuid.uuid4(),
        backend=AgentBackend.codex,
    )
    adapter = AsyncMock()

    await manager._read_stdout(uuid.uuid4(), process, adapter, running)  # type: ignore[arg-type]

    assert running.failure_reason is not None
    assert "longer than limit" in running.failure_reason
    terminate.assert_awaited_once_with(process)
    on_exit.assert_awaited_once()
