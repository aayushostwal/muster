"""Unit tests for ProcessManager._on_process_exit's status-classification
logic -- the single most safety-critical piece of the task lifecycle
refinement: it decides whether a clean agent-process exit silently marks a
task `done`, or hands it back to the user.

test_tasks_api.py deliberately keeps process_manager mocked out and only
tests the HTTP layer (see its docstring). These tests instead drive the real
ProcessManager against the in-memory sqlite test engine (monkeypatching
process_manager.SessionLocal), with a fake asyncio subprocess standing in for
a real Claude/Codex CLI invocation -- there is no cheaper way to exercise
this logic in CI.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings as app_settings
from app.db.models import AgentBackend, Project, Task, TaskStatus
from app.services import process_manager as process_manager_module
from app.services.process_manager import ProcessManager, RunningProcess


class _FakeProcess:
    """Just enough of asyncio.subprocess.Process for _on_process_exit."""

    def __init__(self, exit_code: int):
        self._exit_code = exit_code
        self.returncode: int | None = None
        self.stdin = None

    async def wait(self) -> int:
        self.returncode = self._exit_code
        return self._exit_code


def _make_running(exit_code: int, **kwargs: Any) -> RunningProcess:
    return RunningProcess(
        process=cast(Any, _FakeProcess(exit_code)),
        invocation_id=uuid.uuid4(),
        backend=AgentBackend.claude_code,
        **kwargs,
    )


async def _make_task(session_local) -> uuid.UUID:
    async with session_local() as db:
        project = Project(name="Demo", default_backend=AgentBackend.claude_code)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Do the thing",
            initial_prompt="please do the thing",
            backend=AgentBackend.claude_code,
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


async def _get_task(session_local, task_id: uuid.UUID) -> Task:
    async with session_local() as db:
        task = await db.get(Task, task_id)
        assert task is not None
        return task


@pytest.fixture
def manager(db_engine, monkeypatch):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(process_manager_module, "SessionLocal", session_local)
    return ProcessManager(), session_local


@pytest.mark.asyncio
async def test_clean_exit_does_not_auto_complete_the_task(manager):
    """The core regression this feature fixes: exit_code == 0 must NOT
    become `done` on its own -- it hands control back to the user instead.
    """
    pm, session_local = manager
    task_id = await _make_task(session_local)
    running = _make_running(0)

    await pm._on_process_exit(task_id, running.process, running)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.waiting_on_you
    assert task.attention_reason == "awaiting_review"
    assert task.completed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "previous_status",
    [
        TaskStatus.waiting_on_you,
        TaskStatus.done,
        TaskStatus.failed,
        TaskStatus.cancelled,
    ],
)
async def test_follow_up_reopens_terminal_or_review_state_before_spawning(
    manager, monkeypatch, previous_status
):
    pm, session_local = manager
    task_id = await _make_task(session_local)
    async with session_local() as db:
        task = await db.get(Task, task_id)
        task.status = previous_status
        task.attention_reason = "awaiting_review"
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

    spawn = AsyncMock()
    broadcast = AsyncMock()
    monkeypatch.setattr(pm, "_spawn", spawn)
    monkeypatch.setattr(process_manager_module, "broadcast", broadcast)

    await pm.resume(task_id)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.queued
    assert task.attention_reason is None
    assert task.completed_at is None
    spawn.assert_awaited_once_with(task_id)
    broadcast.assert_awaited_once_with(
        task_id,
        {"type": "status", "status": "queued", "attention_reason": None},
    )


@pytest.mark.asyncio
async def test_cancel_then_exit_finalizes_as_cancelled(manager):
    pm, session_local = manager
    task_id = await _make_task(session_local)
    running = _make_running(0, pending_final_status=TaskStatus.cancelled)

    await pm._on_process_exit(task_id, running.process, running)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.cancelled
    assert task.attention_reason is None
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_complete_then_exit_finalizes_as_done(manager):
    """Mirrors the "Mark conversation complete" click racing a still-running
    process: complete() sets pending_final_status=done and terminates the
    process; once it actually exits, _on_process_exit must honor that
    over the exit code.
    """
    pm, session_local = manager
    task_id = await _make_task(session_local)
    running = _make_running(0, pending_final_status=TaskStatus.done)

    await pm._on_process_exit(task_id, running.process, running)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.done
    assert task.attention_reason is None
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_blocking_question_exit_leaves_status_untouched(manager):
    pm, session_local = manager
    task_id = await _make_task(session_local)
    async with session_local() as db:
        task = await db.get(Task, task_id)
        task.status = TaskStatus.waiting_on_you
        task.attention_reason = "blocking_question"
        await db.commit()

    running = _make_running(0, blocking_question_hit=True)

    await pm._on_process_exit(task_id, running.process, running)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.waiting_on_you
    assert task.attention_reason == "blocking_question"


@pytest.mark.asyncio
async def test_nonzero_exit_with_no_retry_marks_failed(manager, tmp_path, monkeypatch):
    # _append_transcript() on the failure path writes a real file under
    # settings.data_dir (~/.muster/data by default) -- redirect it to a
    # pytest tmp dir so this test never touches the real home directory.
    monkeypatch.setattr(app_settings, "data_dir", tmp_path)

    pm, session_local = manager
    task_id = await _make_task(session_local)
    running = _make_running(1)

    await pm._on_process_exit(task_id, running.process, running)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.failed
    assert task.attention_reason is None
    assert task.completed_at is not None


@pytest.mark.asyncio
async def test_first_terminal_action_wins_without_a_live_process(manager):
    pm, session_local = manager
    task_id = await _make_task(session_local)

    await pm.cancel(task_id)
    await pm.complete(task_id)

    task = await _get_task(session_local, task_id)
    assert task.status == TaskStatus.cancelled
    assert task.completed_at is not None
