from __future__ import annotations

import asyncio
import base64
import sqlite3
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AgentBackend,
    Project,
    RuntimeMode,
    Task,
    TaskInvocation,
    TaskStatus,
)
from app.services.agent_backends.base import AdapterBindings
from app.services import terminal_manager as terminal_manager_module
from app.services.terminal_manager import (
    RunningTerminal,
    TerminalClient,
    TerminalManager,
    _codex_session_ids,
    _wait_for_new_codex_session_id,
)


class _FakeTerminalSession:
    instances: list["_FakeTerminalSession"] = []

    def __init__(self, argv, *, cwd, env, on_output, on_exit, **_kwargs):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.on_output = on_output
        self.on_exit = on_exit
        self.returncode = None
        self.started = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def write(self, _data: bytes) -> None:
        return None

    async def resize(self, _cols: int, _rows: int) -> None:
        return None

    async def terminate(self, _grace_seconds: float = 5.0) -> None:
        return None

    async def wait(self) -> int | None:
        return self.returncode


async def _create_task(
    session_local,
    *,
    status=TaskStatus.queued,
    backend=AgentBackend.codex,
) -> uuid.UUID:
    async with session_local() as db:
        project = Project(name="Terminal project", default_backend=AgentBackend.codex)
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="Interactive task",
            initial_prompt="Fix the bug",
            status=status,
            backend=backend,
            runtime_mode=RuntimeMode.interactive,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id


def _bindings(tmp_path: Path) -> AdapterBindings:
    return AdapterBindings(
        primary_directory=str(tmp_path),
        directories=[str(tmp_path)],
        mcp_servers={},
        tool_rules=[],
        agent_profiles={},
        skills={},
    )


@pytest.mark.asyncio
async def test_codex_session_discovery_waits_for_a_new_task_local_thread(tmp_path):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    index = codex_home / "session_index.jsonl"
    index.write_text('{"id":"old-thread"}\nnot-json\n', encoding="utf-8")
    assert _codex_session_ids(codex_home) == ["old-thread"]

    async def publish_new_thread() -> None:
        await asyncio.sleep(0.01)
        index.write_text(
            '{"id":"old-thread"}\n{"id":"new-thread"}\n',
            encoding="utf-8",
        )

    publisher = asyncio.create_task(publish_new_thread())
    captured = await _wait_for_new_codex_session_id(
        codex_home,
        {"old-thread"},
        attempts=10,
        delay=0.01,
    )
    await publisher

    assert captured == "new-thread"


def test_codex_session_discovery_supports_state_schema_without_created_at_ms(
    tmp_path,
):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    with sqlite3.connect(codex_home / "state_5.sqlite") as connection:
        connection.execute("CREATE TABLE threads (id TEXT, created_at INTEGER)")
        connection.executemany(
            "INSERT INTO threads (id, created_at) VALUES (?, ?)",
            [("older-thread", 1), ("newer-thread", 2)],
        )
        connection.commit()

    assert _codex_session_ids(codex_home) == ["newer-thread", "older-thread"]


@pytest.fixture
def terminal_manager(db_engine, monkeypatch, tmp_path):
    session_local = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(terminal_manager_module, "SessionLocal", session_local)
    monkeypatch.setattr(terminal_manager_module.settings, "data_dir", tmp_path / "muster-data")
    monkeypatch.setattr(terminal_manager_module, "broadcast", AsyncMock())
    monkeypatch.setattr(terminal_manager_module, "TerminalSession", _FakeTerminalSession)
    monkeypatch.setattr(
        terminal_manager_module,
        "_wait_for_new_codex_session_id",
        AsyncMock(return_value=None),
    )
    _FakeTerminalSession.instances.clear()
    structured = SimpleNamespace(
        _load_project=AsyncMock(
            return_value=SimpleNamespace(
                default_backend=AgentBackend.codex,
                default_model=None,
                secrets=[],
            )
        ),
        _bindings_for=AsyncMock(return_value=_bindings(tmp_path)),
        _latest_user_prompt=AsyncMock(return_value=None),
    )
    return TerminalManager(structured), session_local


@pytest.mark.asyncio
async def test_codex_terminal_uses_persistent_task_scoped_home(
    terminal_manager, monkeypatch, tmp_path
):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local)
    expected_home = tmp_path / "muster-data" / "backend-sessions" / str(task_id) / "codex"
    overlay = Mock(return_value=expected_home)
    monkeypatch.setattr(terminal_manager_module, "create_codex_home_overlay", overlay)

    await manager.trigger(task_id)

    overlay.assert_called_once_with([], expected_home)
    assert _FakeTerminalSession.instances[-1].env["CODEX_HOME"] == str(expected_home)
    assert _FakeTerminalSession.instances[-1].started is True
    assert manager._running[task_id].temp_paths == ()

    async with session_local() as db:
        task = await db.get(Task, task_id)
        invocation = (
            await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
        ).scalar_one()
    assert task is not None and task.status == TaskStatus.running
    assert invocation.runtime_mode == RuntimeMode.interactive

    manager._running.pop(task_id).log_file.close()


@pytest.mark.asyncio
async def test_claude_terminals_receive_distinct_persisted_session_ids(terminal_manager):
    manager, session_local = terminal_manager
    first_task_id = await _create_task(session_local, backend=AgentBackend.claude_code)
    second_task_id = await _create_task(session_local, backend=AgentBackend.claude_code)

    await manager.trigger(first_task_id)
    await manager.trigger(second_task_id)

    async with session_local() as db:
        first_task = await db.get(Task, first_task_id)
        second_task = await db.get(Task, second_task_id)
        invocations = (
            await db.execute(
                select(TaskInvocation).where(
                    TaskInvocation.task_id.in_([first_task_id, second_task_id])
                )
            )
        ).scalars().all()

    assert first_task is not None and first_task.session_id is not None
    assert second_task is not None and second_task.session_id is not None
    assert first_task.session_id != second_task.session_id
    assert {item.session_id for item in invocations} == {
        first_task.session_id,
        second_task.session_id,
    }
    for task_id in (first_task_id, second_task_id):
        running = manager._running.pop(task_id)
        assert "--session-id" in running.session.argv
        running.log_file.close()


@pytest.mark.asyncio
async def test_codex_terminal_persists_new_native_session_id(
    terminal_manager, monkeypatch
):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local)
    capture = AsyncMock(return_value="0199aabb-ccdd-7000-8000-000000000001")
    monkeypatch.setattr(
        terminal_manager_module,
        "_wait_for_new_codex_session_id",
        capture,
    )

    await manager.trigger(task_id)
    running = manager._running[task_id]
    assert running.session_capture_task is not None
    await running.session_capture_task

    async with session_local() as db:
        task = await db.get(Task, task_id)
        invocation = (
            await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
        ).scalar_one()

    assert task is not None
    assert task.session_id == "0199aabb-ccdd-7000-8000-000000000001"
    assert invocation.session_id == task.session_id
    capture.assert_awaited_once()
    manager._running.pop(task_id).log_file.close()


@pytest.mark.asyncio
async def test_terminal_setup_failure_marks_task_and_invocation_failed(
    terminal_manager, monkeypatch
):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local)
    monkeypatch.setattr(
        terminal_manager_module,
        "create_codex_home_overlay",
        Mock(side_effect=RuntimeError("storage unavailable")),
    )

    await manager.trigger(task_id)

    assert task_id not in manager._running
    async with session_local() as db:
        task = await db.get(Task, task_id)
        invocation = (
            await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
        ).scalar_one()
    assert task is not None and task.status == TaskStatus.failed
    assert invocation.status == "failed"
    broadcast = terminal_manager_module.broadcast
    assert isinstance(broadcast, AsyncMock)
    assert any(
        call.args[1].get("type") == "invocation"
        and call.args[1]["invocation"]["status"] == "failed"
        for call in broadcast.await_args_list
    )


@pytest.mark.asyncio
async def test_concurrent_restarts_are_serialized(terminal_manager, monkeypatch):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local, status=TaskStatus.done)
    active = 0
    maximum_active = 0

    async def fake_spawn(_task_id, _prompt=None):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.05)
        active -= 1

    monkeypatch.setattr(manager, "_spawn", fake_spawn)

    await asyncio.gather(
        manager.restart_from_beginning(task_id),
        manager.restart_from_beginning(task_id),
    )

    assert maximum_active == 1


@pytest.mark.asyncio
async def test_first_terminal_action_wins_after_session_exit(terminal_manager):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local, status=TaskStatus.waiting_on_you)

    await manager.cancel(task_id)
    await manager.complete(task_id)

    async with session_local() as db:
        task = await db.get(Task, task_id)
    assert task is not None and task.status == TaskStatus.cancelled


@pytest.mark.asyncio
async def test_exit_event_replaces_a_full_client_queue(terminal_manager, tmp_path):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local, status=TaskStatus.running)
    async with session_local() as db:
        invocation = TaskInvocation(
            task_id=task_id,
            sequence=1,
            backend=AgentBackend.codex,
            runtime_mode=RuntimeMode.interactive,
            status="running",
        )
        db.add(invocation)
        await db.commit()
        await db.refresh(invocation)

    log_path = tmp_path / "terminal.log"
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
    queue.put_nowait({"type": "output"})
    running = RunningTerminal(
        task_id=task_id,
        invocation_id=invocation.id,
        session_key="session",
        log_path=log_path,
        log_file=log_path.open("ab", buffering=0),
        clients={"client": TerminalClient(id="client", queue=queue)},
    )
    manager._running[task_id] = running

    await manager._on_exit(running, 0)

    assert (await queue.get())["type"] == "exit"
    assert task_id not in manager._running


@pytest.mark.asyncio
async def test_archive_attach_cannot_deadlock_with_small_queue_config(
    terminal_manager, monkeypatch
):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local, status=TaskStatus.waiting_on_you)
    monkeypatch.setattr(terminal_manager_module.settings, "terminal_client_queue_frames", 1)

    _client_id, queue = await asyncio.wait_for(
        manager.attach(task_id, cols=80, rows=24), timeout=1
    )

    assert queue.qsize() == 2
    assert (await queue.get())["type"] == "ready"
    assert (await queue.get())["type"] == "exit"


@pytest.mark.asyncio
async def test_attach_replays_new_session_when_client_sequence_is_ahead(
    terminal_manager, tmp_path
):
    manager, session_local = terminal_manager
    task_id = await _create_task(session_local, status=TaskStatus.running)
    log_path = tmp_path / "terminal.log"
    running = RunningTerminal(
        task_id=task_id,
        invocation_id=uuid.uuid4(),
        session_key="new-session",
        log_path=log_path,
        log_file=log_path.open("ab", buffering=0),
        replay=deque([(1, b"current session")]),
        replay_size=len(b"current session"),
        next_seq=2,
    )
    manager._running[task_id] = running

    _client_id, queue = await manager.attach(task_id, cols=80, rows=24, after_seq=99)

    assert (await queue.get())["type"] == "ready"
    assert (await queue.get())["type"] == "gap"
    output = await queue.get()
    assert output["type"] == "output"
    assert base64.b64decode(output["data_b64"]) == b"current session"
    manager._running.pop(task_id).log_file.close()
