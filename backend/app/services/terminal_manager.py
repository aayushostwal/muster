"""Lifecycle manager for native Codex/Claude terminal sessions."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select

from app.api.routes.ws import broadcast
from app.config import settings
from app.core.security import decrypt_secret
from app.db.models import (
    AgentBackend,
    Message,
    MessageSender,
    RuntimeMode,
    Task,
    TaskInvocation,
    TaskStatus,
)
from app.db.session import SessionLocal
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import CodexAdapter, create_codex_home_overlay
from app.services.terminal_session import TerminalSession

logger = logging.getLogger(__name__)

_ADAPTERS = {
    AgentBackend.claude_code: ClaudeCodeAdapter(),
    AgentBackend.codex: CodexAdapter(),
}


@dataclass
class TerminalClient:
    id: str
    queue: asyncio.Queue[dict]
    writable: bool = False


@dataclass
class RunningTerminal:
    task_id: uuid.UUID
    invocation_id: uuid.UUID
    session_key: str
    log_path: Path
    log_file: BinaryIO
    temp_paths: tuple[Path, ...] = ()
    session: TerminalSession | None = None
    clients: dict[str, TerminalClient] = field(default_factory=dict)
    controller_id: str | None = None
    replay: deque[tuple[int, bytes]] = field(default_factory=deque)
    replay_size: int = 0
    next_seq: int = 1
    final_status: TaskStatus | None = None
    restarting: bool = False
    shutting_down: bool = False


class TerminalManager:
    def __init__(self, structured_manager: Any) -> None:
        self._structured = structured_manager
        self._running: dict[uuid.UUID, RunningTerminal] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def _lock_for(self, task_id: uuid.UUID) -> asyncio.Lock:
        return self._locks.setdefault(task_id, asyncio.Lock())

    async def trigger(self, task_id: uuid.UUID, prompt: str | None = None) -> None:
        async with self._lock_for(task_id):
            if task_id in self._running:
                return
            await self._spawn(task_id, prompt)

    async def _spawn(self, task_id: uuid.UUID, prompt: str | None = None) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None or task.status in {TaskStatus.done, TaskStatus.cancelled}:
                return
            project = await self._structured._load_project(db, task.project_id)
            if project is None:
                await self._fail_task(task_id, "Project not found for interactive terminal")
                return
            bindings = await self._structured._bindings_for(db, project, task)
            if not bindings.primary_directory or not Path(bindings.primary_directory).is_dir():
                await self._fail_task(
                    task_id,
                    "Choose an available primary project directory before starting the terminal.",
                )
                return
            secrets = {secret.key_name: decrypt_secret(secret.encrypted_value) for secret in project.secrets}
            adapter = _ADAPTERS[task.backend]
            command = adapter.build_interactive_command(
                task,
                project,
                bindings,
                secrets,
                prompt=prompt or task.initial_prompt,
            )

            if task.git_baseline_captured_at is None:
                from app.services.pr_delivery import capture_git_baseline

                baseline = await capture_git_baseline(bindings.primary_directory)
                if baseline is not None:
                    task.git_baseline_dirty_paths = baseline
                    task.git_baseline_captured_at = datetime.now(timezone.utc)

            previous = await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
            invocation = TaskInvocation(
                task_id=task_id,
                sequence=len(previous.scalars().all()) + 1,
                backend=task.backend,
                runtime_mode=RuntimeMode.interactive,
                model=task.model or (
                    project.default_model if task.backend == project.default_backend else None
                ),
                thinking_level=task.thinking_level,
                status="running",
            )
            task.status = TaskStatus.running
            task.attention_reason = None
            task.completed_at = None
            if task.started_at is None:
                task.started_at = datetime.now(timezone.utc)
            db.add(invocation)
            await db.commit()
            await db.refresh(invocation)

        running: RunningTerminal | None = None
        try:
            terminal_dir = settings.terminals_dir / str(task_id)
            terminal_dir.mkdir(parents=True, exist_ok=True)
            terminal_dir.chmod(0o700)
            log_path = terminal_dir / f"{invocation.id}.ttylog"
            log_file = log_path.open("ab", buffering=0)
            log_path.chmod(0o600)
            running = RunningTerminal(
                task_id=task_id,
                invocation_id=invocation.id,
                session_key=str(uuid.uuid4()),
                log_path=log_path,
                log_file=log_file,
                temp_paths=_command_temp_paths(command.argv),
            )

            async def on_output(data: bytes) -> None:
                await self._on_output(running, data)

            async def on_exit(exit_code: int) -> None:
                await self._on_exit(running, exit_code)

            runtime_env = {**os.environ, **secrets}
            if task.backend == AgentBackend.codex:
                codex_home = create_codex_home_overlay(
                    bindings.tool_rules,
                    settings.backend_sessions_dir / str(task_id) / AgentBackend.codex.value,
                )
                runtime_env["CODEX_HOME"] = str(codex_home)

            session = TerminalSession(
                command.argv,
                cwd=bindings.primary_directory,
                env=runtime_env,
                on_output=on_output,
                on_exit=on_exit,
            )
            running.session = session
            self._running[task_id] = running
            await broadcast(
                task_id,
                {"type": "status", "status": TaskStatus.running.value, "attention_reason": None},
            )
            await broadcast(
                task_id,
                {"type": "invocation", "invocation": _serialize_invocation(invocation)},
            )
            await session.start()
        except Exception as exc:  # noqa: BLE001 - any runtime setup failure must finalize the task
            self._running.pop(task_id, None)
            if running is not None:
                running.log_file.close()
                _cleanup_temp_paths(running.temp_paths)
            else:
                _cleanup_temp_paths(_command_temp_paths(command.argv))
            await self._mark_start_failed(
                task_id,
                invocation.id,
                f"Unable to start interactive terminal: {exc}",
            )

    async def _on_output(self, running: RunningTerminal, data: bytes) -> None:
        if not data:
            return
        try:
            running.log_file.write(data)
        except OSError:
            logger.warning("failed to write terminal log for task %s", running.task_id, exc_info=True)
        seq = running.next_seq
        running.next_seq += 1
        running.replay.append((seq, data))
        running.replay_size += len(data)
        while running.replay and running.replay_size > settings.terminal_replay_bytes:
            _, discarded = running.replay.popleft()
            running.replay_size -= len(discarded)
        event = {"type": "output", "seq": seq, "data_b64": base64.b64encode(data).decode("ascii")}
        for client in list(running.clients.values()):
            try:
                client.queue.put_nowait(event)
            except asyncio.QueueFull:
                while not client.queue.empty():
                    client.queue.get_nowait()
                client.queue.put_nowait(
                    {"type": "error", "code": "slow_client", "message": "Terminal output consumer fell behind"}
                )
                running.clients.pop(client.id, None)
                if running.controller_id == client.id:
                    running.controller_id = None
        self._grant_next_controller(running)

    async def attach(
        self, task_id: uuid.UUID, *, cols: int, rows: int, after_seq: int = 0
    ) -> tuple[str, asyncio.Queue[dict]]:
        client_id = str(uuid.uuid4())
        # attach() queues ready + gap + replay before the sender task starts;
        # never allow a small/invalid config value to deadlock that handshake.
        queue: asyncio.Queue[dict] = asyncio.Queue(
            maxsize=max(4, settings.terminal_client_queue_frames)
        )
        running = self._running.get(task_id)
        if running is None:
            await self._enqueue_archive(task_id, queue)
            return client_id, queue
        client = TerminalClient(id=client_id, queue=queue)
        running.clients[client_id] = client
        if running.controller_id is None:
            running.controller_id = client_id
            client.writable = True
        oldest = running.replay[0][0] if running.replay else running.next_seq
        latest = running.next_seq - 1
        await queue.put(
            {
                "type": "ready",
                "session": running.session_key,
                "control": "granted" if client.writable else "read_only",
                "oldest_seq": oldest,
                "latest_seq": latest,
            }
        )
        replay_after = after_seq
        if after_seq > latest:
            # The browser was attached to an older invocation whose sequence
            # space no longer applies. Reset and send this session's replay.
            await queue.put({"type": "gap", "oldest_seq": oldest})
            replay_after = 0
        elif after_seq and after_seq < oldest - 1:
            await queue.put({"type": "gap", "oldest_seq": oldest})
        replay = [(seq, data) for seq, data in running.replay if seq > replay_after]
        if replay:
            await queue.put(
                {
                    "type": "output",
                    "seq": replay[-1][0],
                    "data_b64": base64.b64encode(b"".join(data for _, data in replay)).decode("ascii"),
                }
            )
        if client.writable and running.session is not None:
            await running.session.resize(cols, rows)
        return client_id, queue

    async def _enqueue_archive(self, task_id: uuid.UUID, queue: asyncio.Queue[dict]) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                raise KeyError("Task not found")
            if task.runtime_mode != RuntimeMode.interactive:
                raise ValueError("Task does not use the interactive terminal runtime")
            result = await db.execute(
                select(TaskInvocation)
                .where(
                    TaskInvocation.task_id == task_id,
                    TaskInvocation.runtime_mode == RuntimeMode.interactive,
                )
                .order_by(TaskInvocation.started_at.desc())
                .limit(1)
            )
            invocation = result.scalar_one_or_none()
        await queue.put(
            {"type": "ready", "session": None, "control": "read_only", "oldest_seq": 0, "latest_seq": 0}
        )
        if invocation is not None:
            path = settings.terminals_dir / str(task_id) / f"{invocation.id}.ttylog"
            try:
                with path.open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    size = stream.tell()
                    stream.seek(max(0, size - settings.terminal_replay_bytes))
                    data = stream.read()
                if data:
                    await queue.put(
                        {"type": "output", "seq": 1, "data_b64": base64.b64encode(data).decode("ascii")}
                    )
            except OSError:
                pass
        await queue.put(
            {"type": "exit", "exit_code": None, "status": task.status.value, "archived": True}
        )

    async def detach(self, task_id: uuid.UUID, client_id: str) -> None:
        running = self._running.get(task_id)
        if running is None:
            return
        running.clients.pop(client_id, None)
        if running.controller_id == client_id:
            running.controller_id = None
            self._grant_next_controller(running)

    async def take_control(self, task_id: uuid.UUID, client_id: str) -> None:
        running = self._require_running(task_id)
        client = running.clients.get(client_id)
        if client is None:
            raise KeyError("Terminal client is not attached")
        previous = running.clients.get(running.controller_id or "")
        if previous is not None:
            previous.writable = False
            self._put_control(previous, "read_only")
        running.controller_id = client_id
        client.writable = True
        self._put_control(client, "granted")

    async def input(self, task_id: uuid.UUID, client_id: str, data: bytes) -> None:
        running = self._require_running(task_id)
        if running.controller_id != client_id:
            raise PermissionError("This terminal is controlled by another browser")
        if running.session is not None:
            await running.session.write(data)

    async def resize(self, task_id: uuid.UUID, client_id: str, cols: int, rows: int) -> None:
        running = self._require_running(task_id)
        if running.controller_id != client_id:
            return
        if running.session is not None:
            await running.session.resize(cols, rows)

    async def resume(self, task_id: uuid.UUID) -> None:
        async with self._lock_for(task_id):
            prompt = await self._structured._latest_user_prompt(task_id)
            running = self._running.get(task_id)
            if running is not None and running.session is not None and prompt:
                await running.session.write(prompt.encode("utf-8") + b"\r")
                return
            if running is None:
                await self._spawn(task_id, prompt)

    async def cancel(self, task_id: uuid.UUID) -> None:
        await self._finish(task_id, TaskStatus.cancelled)

    async def complete(self, task_id: uuid.UUID) -> None:
        await self._finish(task_id, TaskStatus.done)

    async def _finish(self, task_id: uuid.UUID, status: TaskStatus) -> None:
        async with self._lock_for(task_id):
            running = self._running.get(task_id)
            if running is None:
                await self._set_status(task_id, status, completed=True)
                return
            running.final_status = status
            if running.session is not None:
                await running.session.terminate()
                await running.session.wait()
            # If the process had already begun its natural-exit callback when
            # the click arrived, that callback may have classified it first.
            # Reassert the explicit user action before returning the API call.
            await self._set_status(task_id, status, completed=True)

    async def restart_from_beginning(self, task_id: uuid.UUID) -> None:
        async with self._lock_for(task_id):
            running = self._running.get(task_id)
            if running is not None:
                running.restarting = True
                if running.session is not None:
                    await running.session.terminate()
                    await running.session.wait()
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None:
                    return
                task.status = TaskStatus.queued
                task.attention_reason = None
                task.completed_at = None
                task.session_id = None
                await db.commit()
            await self._spawn(task_id)

    async def retry_now(self, task_id: uuid.UUID) -> None:
        async with self._lock_for(task_id):
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None or task.status != TaskStatus.failed:
                    return
                task.status = TaskStatus.queued
                task.completed_at = None
                task.attention_reason = None
                await db.commit()
            await self._spawn(task_id)

    async def switch_backend(self, task_id: uuid.UUID, backend: AgentBackend) -> None:
        async with self._lock_for(task_id):
            running = self._running.get(task_id)
            if running is not None:
                running.restarting = True
                if running.session is not None:
                    await running.session.terminate()
                    await running.session.wait()
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None:
                    return
                task.backend = backend
                task.model = None
                task.fallback_models = []
                task.agent_id = None
                task.session_id = None
                task.status = TaskStatus.queued
                task.attention_reason = None
                task.completed_at = None
                await db.commit()
            await self._spawn(task_id)

    async def shutdown(self) -> None:
        running_sessions = list(self._running.values())
        for running in running_sessions:
            running.shutting_down = True
        await asyncio.gather(
            *(
                running.session.terminate()
                for running in running_sessions
                if running.session is not None
            ),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(
                running.session.wait()
                for running in running_sessions
                if running.session is not None
            ),
            return_exceptions=True,
        )

    async def _on_exit(self, running: RunningTerminal, exit_code: int) -> None:
        if self._running.get(running.task_id) is not running:
            return
        try:
            running.log_file.close()
        except OSError:
            pass
        _cleanup_temp_paths(running.temp_paths)
        if running.restarting:
            status = TaskStatus.queued
            attention_reason = None
            completed = False
            invocation_status = "restarted"
        elif running.shutting_down:
            status = TaskStatus.waiting_on_you
            attention_reason = "awaiting_review"
            completed = False
            invocation_status = "interrupted"
        elif running.final_status is not None:
            status = running.final_status
            attention_reason = None
            completed = True
            invocation_status = status.value
        elif exit_code == 0:
            status = TaskStatus.waiting_on_you
            attention_reason = "awaiting_review"
            completed = False
            invocation_status = "completed"
        else:
            status = TaskStatus.failed
            attention_reason = None
            completed = True
            invocation_status = "failed"

        async with SessionLocal() as db:
            task = await db.get(Task, running.task_id)
            invocation = await db.get(TaskInvocation, running.invocation_id)
            if task is not None:
                task.status = status
                task.attention_reason = attention_reason
                task.completed_at = datetime.now(timezone.utc) if completed else None
            if invocation is not None:
                invocation.status = invocation_status
                invocation.completed_at = datetime.now(timezone.utc)
            await db.commit()
            if invocation is not None:
                await db.refresh(invocation)

        event = {"type": "exit", "exit_code": exit_code, "status": status.value}
        for client in list(running.clients.values()):
            try:
                client.queue.put_nowait(event)
            except asyncio.QueueFull:
                while not client.queue.empty():
                    client.queue.get_nowait()
                client.queue.put_nowait(event)
        self._running.pop(running.task_id, None)
        await broadcast(
            running.task_id,
            {"type": "status", "status": status.value, "attention_reason": attention_reason},
        )
        if invocation is not None:
            await broadcast(
                running.task_id,
                {"type": "invocation", "invocation": _serialize_invocation(invocation)},
            )

    async def _mark_start_failed(
        self, task_id: uuid.UUID, invocation_id: uuid.UUID, message: str
    ) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            invocation = await db.get(TaskInvocation, invocation_id)
            if task is not None:
                task.status = TaskStatus.failed
                task.completed_at = datetime.now(timezone.utc)
            if invocation is not None:
                invocation.status = "failed"
                invocation.completed_at = datetime.now(timezone.utc)
            db.add(Message(task_id=task_id, sender=MessageSender.system, content_text=message))
            await db.commit()
            if invocation is not None:
                await db.refresh(invocation)
        await broadcast(
            task_id,
            {"type": "status", "status": TaskStatus.failed.value, "attention_reason": None},
        )
        if invocation is not None:
            await broadcast(
                task_id,
                {"type": "invocation", "invocation": _serialize_invocation(invocation)},
            )

    async def _fail_task(self, task_id: uuid.UUID, message: str) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            task.status = TaskStatus.failed
            task.completed_at = datetime.now(timezone.utc)
            db.add(Message(task_id=task_id, sender=MessageSender.system, content_text=message))
            await db.commit()
        await broadcast(
            task_id,
            {"type": "status", "status": TaskStatus.failed.value, "attention_reason": None},
        )

    async def _set_status(self, task_id: uuid.UUID, status: TaskStatus, *, completed: bool) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            if task.status in {TaskStatus.done, TaskStatus.cancelled}:
                return
            task.status = status
            task.attention_reason = None
            task.completed_at = datetime.now(timezone.utc) if completed else None
            await db.commit()
        await broadcast(
            task_id,
            {"type": "status", "status": status.value, "attention_reason": None},
        )

    def _require_running(self, task_id: uuid.UUID) -> RunningTerminal:
        running = self._running.get(task_id)
        if running is None:
            raise KeyError("Terminal session is not running")
        return running

    @staticmethod
    def _put_control(client: TerminalClient, state: str) -> None:
        try:
            client.queue.put_nowait({"type": "control", "state": state})
        except asyncio.QueueFull:
            pass

    def _grant_next_controller(self, running: RunningTerminal) -> None:
        if running.controller_id is not None or not running.clients:
            return
        client = next(iter(running.clients.values()))
        client.writable = True
        running.controller_id = client.id
        self._put_control(client, "granted")


def _serialize_invocation(invocation: TaskInvocation) -> dict:
    return {
        "id": str(invocation.id),
        "task_id": str(invocation.task_id),
        "sequence": invocation.sequence,
        "backend": invocation.backend.value,
        "runtime_mode": (
            invocation.runtime_mode.value
            if isinstance(invocation.runtime_mode, RuntimeMode)
            else invocation.runtime_mode
        ),
        "session_id": invocation.session_id,
        "model": invocation.model,
        "thinking_level": invocation.thinking_level,
        "status": invocation.status,
        "input_tokens": invocation.input_tokens,
        "output_tokens": invocation.output_tokens,
        "cached_tokens": invocation.cached_tokens,
        "started_at": invocation.started_at.isoformat(),
        "completed_at": invocation.completed_at.isoformat() if invocation.completed_at else None,
    }


def _command_temp_paths(argv: list[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for index, value in enumerate(argv[:-1]):
        if value == "--mcp-config":
            candidate = Path(argv[index + 1])
            if candidate.name.startswith("muster-mcp-"):
                paths.append(candidate)
    return tuple(paths)


def _cleanup_temp_paths(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to remove terminal runtime temp file %s", path, exc_info=True)
