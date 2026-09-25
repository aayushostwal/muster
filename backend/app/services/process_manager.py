"""Process manager: spawns/streams/retries backend CLI subprocesses.

Single in-process asyncio-based singleton holding at most one live
subprocess per Task (see docs/SPEC.md "Process manager" and
"Integration seams").
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import shlex
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.ws import broadcast
from app.config import settings
from app.core.security import decrypt_secret
from app.db.models import (
    AgentBackend,
    AgentProfile,
    DirectoryBinding,
    GlobalMcpServer,
    GlobalTool,
    FailureClass,
    Message,
    MessageSender,
    Project,
    ProjectCapabilityOverride,
    RuntimeMode,
    Skill,
    Task,
    TaskBackendSession,
    TaskEvent,
    TaskInvocation,
    TaskRunAttempt,
    TaskStatus,
    ToolApprovalRequest,
)
from app.db.session import SessionLocal
from app.services import retry
from app.services.agent_backends.base import (
    AdapterBindings,
    ActivityEvent,
    AgentBackendAdapter,
    AgentText,
    BlockingQuestion,
    Done,
    ErrorEvent,
    ParsedEvent,
    PermissionRequest,
    SessionId,
    UsageEvent,
)
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import (
    CodexAdapter,
    create_codex_home_overlay,
    repair_codex_rollout_path,
)

logger = logging.getLogger(__name__)

_ADAPTERS: dict[AgentBackend, AgentBackendAdapter] = {
    AgentBackend.claude_code: ClaudeCodeAdapter(),
    AgentBackend.codex: CodexAdapter(),
}

_STDERR_TAIL_LIMIT = 4000
_FORCE_KILL_GRACE = 5.0


def _default_backend_session_path(task_id: uuid.UUID, backend: AgentBackend) -> str:
    return f"backend-sessions/{task_id}/{backend.value}"


def _resolve_backend_session_path(storage_path: str) -> Path:
    """Resolve a persisted relative path and keep it inside Muster's data dir."""
    data_dir = settings.data_dir.resolve()
    resolved = (settings.data_dir / storage_path).resolve()
    try:
        resolved.relative_to(data_dir)
    except ValueError as exc:
        raise RuntimeError("Backend session storage escaped MUSTER_DATA_DIR") from exc
    return resolved


async def _get_or_create_backend_session(
    db: AsyncSession, task: Task
) -> TaskBackendSession:
    session = (
        await db.execute(
            select(TaskBackendSession).where(TaskBackendSession.task_id == task.id)
        )
    ).scalar_one_or_none()
    expected_path = _default_backend_session_path(task.id, task.backend)
    if session is None:
        session = TaskBackendSession(
            task_id=task.id,
            backend=task.backend,
            session_id=task.session_id,
            storage_path=expected_path,
        )
        db.add(session)
        await db.flush()
        return session

    if session.backend != task.backend:
        session.backend = task.backend
        session.session_id = task.session_id
        session.storage_path = expected_path
    elif session.session_id is None and task.session_id is not None:
        # Backward-compatible adoption of Task.session_id during rollout.
        session.session_id = task.session_id
    elif task.session_id != session.session_id:
        # The dedicated row is authoritative after migration; keep the legacy
        # API field synchronized until it can be removed separately.
        task.session_id = session.session_id
    return session


@dataclass
class RunningProcess:
    process: asyncio.subprocess.Process
    invocation_id: uuid.UUID
    backend: AgentBackend
    temp_paths: tuple[Path, ...] = ()
    reader_task: asyncio.Task | None = None
    stderr_task: asyncio.Task | None = None
    stderr_buf: bytearray = field(default_factory=bytearray)
    blocking_question_hit: bool = False
    cancel_requested: bool = False
    restart_requested: bool = False
    switch_requested: bool = False
    # Set by cancel()/complete() to tell _on_process_exit which terminal
    # status to finalize as once the (possibly just-terminated) process
    # actually exits, instead of running the normal done/failed/retry
    # classification. None means "let _on_process_exit decide normally".
    pending_final_status: TaskStatus | None = None
    pending_tool_calls: dict[str, tuple[str, dict]] = field(default_factory=dict)
    permission_requests: set[str] = field(default_factory=set)
    watchdog_task: asyncio.Task | None = None
    started_monotonic: float = field(default_factory=time.monotonic)
    last_activity_monotonic: float = field(default_factory=time.monotonic)
    received_event: bool = False
    failure_reason: str | None = None


class ProcessManager:
    """Owns at most one live subprocess per Task."""

    def __init__(self) -> None:
        self._running: dict[uuid.UUID, RunningProcess] = {}
        self._pending_retries: dict[uuid.UUID, asyncio.Task] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def _lock_for(self, task_id: uuid.UUID) -> asyncio.Lock:
        lock = self._locks.get(task_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[task_id] = lock
        return lock

    # -- public API (see docs/SPEC.md "Integration seams") ------------------

    async def trigger(self, task_id: uuid.UUID) -> None:
        await self._trigger(task_id, reopen=False)

    async def resume(self, task_id: uuid.UUID) -> None:
        """Resume a task after a newly persisted user message.

        Reopening and spawning share the same lifecycle lock, so an explicit
        cancel/complete cannot be lost between the route's DB commit and the
        next subprocess start.
        """
        await self._trigger(task_id, reopen=True)

    async def _trigger(self, task_id: uuid.UUID, *, reopen: bool) -> None:
        while True:
            reader_task: asyncio.Task | None = None
            async with self._lock_for(task_id):
                running = self._running.get(task_id)
                if running is None:
                    if reopen:
                        await self._reopen_for_follow_up(task_id)
                    await self._spawn(task_id)
                    return
                if running.pending_final_status is None and running.process.returncode is None:
                    if await self._deliver_to_running(task_id, running):
                        return
                # Wait outside the lock for the old turn's exit handler to
                # commit its status and release this task's lifecycle slot.
                # Otherwise it can overwrite a newly resumed follow-up turn.
                reader_task = running.reader_task

            if reader_task is None or reader_task is asyncio.current_task():
                await asyncio.sleep(0)
            else:
                await asyncio.shield(reader_task)

    async def reconcile_interrupted_tasks(self) -> int:
        """Move database-only `running` rows to an actionable state on startup."""
        now = datetime.now(timezone.utc)
        message_text = (
            "Muster restarted while this agent invocation was running. The prior runtime "
            "is no longer attached; review the task and send a message to continue."
        )
        async with SessionLocal() as db:
            tasks = (
                await db.execute(select(Task).where(Task.status == TaskStatus.running))
            ).scalars().all()
            if not tasks:
                return 0
            task_ids = [task.id for task in tasks]
            invocations = (
                await db.execute(
                    select(TaskInvocation).where(
                        TaskInvocation.task_id.in_(task_ids),
                        TaskInvocation.status == "running",
                    )
                )
            ).scalars().all()
            for task in tasks:
                task.status = TaskStatus.waiting_on_you
                task.completed_at = None
                db.add(
                    Message(
                        task_id=task.id,
                        sender=MessageSender.system,
                        content_text=message_text,
                    )
                )
            for invocation in invocations:
                invocation.status = "interrupted"
                invocation.completed_at = now
            await db.commit()
        for task_id in task_ids:
            await self._append_transcript(task_id, "system", message_text)
        logger.warning("reconciled %d interrupted task(s)", len(task_ids))
        return len(task_ids)

    async def shutdown(self) -> None:
        """Stop every managed runtime so child processes cannot outlive Muster."""
        active = list(self._running.values())
        for running in active:
            if running.process.returncode is None:
                running.failure_reason = "Muster shut down while the agent runtime was active."
        await asyncio.gather(
            *(self._terminate_process_tree(running.process) for running in active),
            return_exceptions=True,
        )
        readers = [
            running.reader_task
            for running in active
            if running.reader_task is not None and not running.reader_task.done()
        ]
        if readers:
            await asyncio.gather(*readers, return_exceptions=True)

    async def cancel(self, task_id: uuid.UUID) -> None:
        await self._finish_as(task_id, TaskStatus.cancelled)

    async def complete(self, task_id: uuid.UUID) -> None:
        """Explicitly close out a task at the user's request ("Mark conversation
        complete"). This is the ONLY path that marks a task `done` today.

        Extension point: a clean agent-process exit does NOT call this. If
        the app later gains a trusted, structured delivery signal (e.g. a
        verified PR merge webhook, or a signed Canvas "delivered" event),
        `_on_process_exit`'s clean-exit branch could invoke `complete()`
        automatically once that signal is present and verified. Until then,
        completion must stay an explicit user action -- never infer it from
        assistant prose or a bare zero exit code.
        """
        await self._finish_as(task_id, TaskStatus.done)

    async def retry_now(self, task_id: uuid.UUID) -> None:
        async with self._lock_for(task_id):
            pending = self._pending_retries.pop(task_id, None)
            if pending is not None:
                pending.cancel()
        await self.trigger(task_id)

    async def restart_from_beginning(self, task_id: uuid.UUID) -> None:
        """Start the task's original brief in a new native CLI session.

        This is intentionally different from retrying or sending a follow-up:
        any live invocation is stopped, the backend resume handle is discarded,
        and ``_spawn`` takes its fresh-session path using ``initial_prompt``.
        Conversation and invocation history remain available for auditability.
        """
        async with self._lock_for(task_id):
            pending_retry = self._pending_retries.pop(task_id, None)
            if pending_retry is not None:
                pending_retry.cancel()

            running = self._running.get(task_id)
            if running is not None:
                if running.pending_final_status is not None:
                    # A cancel/complete click won the lifecycle race. Do not
                    # reinterpret that explicit outcome as a restart.
                    return
                # _on_process_exit must not classify this intentional stop as a
                # user cancellation or schedule a retry before the fresh run.
                running.restart_requested = True
                if running.process.returncode is None:
                    await self._terminate_process_tree(running.process)
                if (
                    running.reader_task is not None
                    and running.reader_task is not asyncio.current_task()
                ):
                    await running.reader_task

            now = datetime.now(timezone.utc)
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None:
                    logger.warning("restart requested for unknown task %s", task_id)
                    return

                task.status = TaskStatus.queued
                task.attention_reason = None
                task.session_id = None
                backend_session = (
                    await db.execute(
                        select(TaskBackendSession).where(TaskBackendSession.task_id == task_id)
                    )
                ).scalar_one_or_none()
                if backend_session is not None:
                    backend_session.session_id = None
                task.started_at = None
                task.completed_at = None

                pending_approvals = (
                    await db.execute(
                        select(ToolApprovalRequest).where(
                            ToolApprovalRequest.task_id == task_id,
                            ToolApprovalRequest.status == "pending",
                        )
                    )
                ).scalars().all()
                for approval in pending_approvals:
                    approval.status = "superseded"
                    approval.resolution_scope = "restart"
                    approval.resolved_at = now

                message = Message(
                    task_id=task_id,
                    sender=MessageSender.system,
                    content_text=(
                        "Restarted from the beginning in a new agent session. "
                        "The original brief is being sent again."
                    ),
                )
                db.add(message)
                await db.commit()
                await db.refresh(message)
                for approval in pending_approvals:
                    await db.refresh(approval)

            await self._append_transcript(task_id, "system", message.content_text or "")
            await broadcast(task_id, {"type": "status", "status": TaskStatus.queued.value})
            await broadcast(
                task_id, {"type": "message", "message": _serialize_message(message)}
            )
            for approval in pending_approvals:
                await broadcast(
                    task_id,
                    {"type": "tool_approval", "approval": _serialize_tool_approval(approval)},
                )

            await self._spawn(task_id)

    async def switch_backend(self, task_id: uuid.UUID, backend: AgentBackend) -> None:
        """Move an existing task to another runtime using a fresh native session.

        Backend session handles and model identifiers are runtime-specific, so
        neither is carried across the boundary. The prior task conversation is
        converted into a bounded handoff prompt for the first invocation on the
        new backend; persisted messages and invocation telemetry remain intact.
        """
        async with self._lock_for(task_id):
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None:
                    logger.warning("runtime switch requested for unknown task %s", task_id)
                    return
                if task.backend == backend:
                    return
                previous_backend = task.backend

            pending_retry = self._pending_retries.pop(task_id, None)
            if pending_retry is not None:
                pending_retry.cancel()

            running = self._running.get(task_id)
            if running is not None:
                if running.pending_final_status is not None:
                    # Preserve the first explicit terminal action under rapid
                    # clicks instead of switching a task while it is closing.
                    return
                # Prevent normal exit classification while the old runtime is
                # intentionally replaced by a fresh backend invocation.
                running.switch_requested = True
                if running.process.returncode is None:
                    await self._terminate_process_tree(running.process)
                if (
                    running.reader_task is not None
                    and running.reader_task is not asyncio.current_task()
                ):
                    await running.reader_task
            now = datetime.now(timezone.utc)
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                if task is None:
                    return
                # Build the handoff after the previous process has fully
                # exited so its final persisted output is not omitted.
                handoff_prompt = await self._runtime_handoff_prompt_db(
                    db, task, previous_backend, backend
                )
                # A selected agent and model chain may only exist on the old
                # runtime. Fall back to the destination runtime's defaults.
                task.backend = backend
                task.agent_id = None
                task.model = None
                task.fallback_models = []
                task.session_id = None
                backend_session = (
                    await db.execute(
                        select(TaskBackendSession).where(TaskBackendSession.task_id == task_id)
                    )
                ).scalar_one_or_none()
                if backend_session is not None:
                    backend_session.backend = backend
                    backend_session.session_id = None
                    backend_session.storage_path = _default_backend_session_path(task_id, backend)
                task.status = TaskStatus.queued
                task.attention_reason = None
                task.completed_at = None

                pending_approvals = (
                    await db.execute(
                        select(ToolApprovalRequest).where(
                            ToolApprovalRequest.task_id == task_id,
                            ToolApprovalRequest.status == "pending",
                        )
                    )
                ).scalars().all()
                for approval in pending_approvals:
                    approval.status = "superseded"
                    approval.resolution_scope = "runtime_switch"
                    approval.resolved_at = now

                message = Message(
                    task_id=task_id,
                    sender=MessageSender.system,
                    content_text=(
                        f"Runtime switched from {_backend_label(previous_backend)} to "
                        f"{_backend_label(backend)}. A fresh {_backend_label(backend)} "
                        "session is starting with a handoff of the prior conversation. "
                        "Runtime-specific agent and model selections were reset."
                    ),
                )
                db.add(message)
                await db.commit()
                await db.refresh(message)
                for approval in pending_approvals:
                    await db.refresh(approval)

            await self._append_transcript(task_id, "system", message.content_text or "")
            await broadcast(task_id, {"type": "status", "status": TaskStatus.queued.value})
            await broadcast(
                task_id, {"type": "message", "message": _serialize_message(message)}
            )
            for approval in pending_approvals:
                await broadcast(
                    task_id,
                    {"type": "tool_approval", "approval": _serialize_tool_approval(approval)},
                )

            await self._spawn(task_id, initial_prompt=handoff_prompt)

    async def resume_after_approval(self, task_id: uuid.UUID) -> None:
        """Stop an approval-blocked CLI turn, then resume it with the new rule set."""
        running = self._running.get(task_id)
        if running is not None and running.process.returncode is None:
            await self._terminate_process_tree(running.process)
            if running.reader_task is not None and running.reader_task is not asyncio.current_task():
                await running.reader_task
        await self.trigger(task_id)

    @staticmethod
    async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
        """Terminate the runtime session, including shell and MCP descendants."""
        if process.returncode is not None:
            return
        try:
            if os.name == "posix" and getattr(process, "pid", None):
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=_FORCE_KILL_GRACE)
        except asyncio.TimeoutError:
            try:
                if os.name == "posix" and getattr(process, "pid", None):
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    async def _finish_as(self, task_id: uuid.UUID, status: TaskStatus) -> None:
        """Stop a turn and return only after its Task reaches a final state.

        The first terminal action wins if multiple cancel/complete requests
        arrive while one process is exiting. Every caller waits for the same
        reader, so an action response cannot expose stale `running` state.
        """
        reader_task: asyncio.Task | None = None
        async with self._lock_for(task_id):
            pending = self._pending_retries.pop(task_id, None)
            if pending is not None:
                pending.cancel()

            running = self._running.get(task_id)
            if running is None:
                async with SessionLocal() as db:
                    task = await db.get(Task, task_id)
                    if task is None or task.status in (TaskStatus.done, TaskStatus.cancelled):
                        # Terminal actions are idempotent. Once a concurrent
                        # complete/cancel wins, a later rapid click cannot
                        # rewrite that outcome.
                        return
                await self._set_status(task_id, status, completed=True)
                return
            if running.pending_final_status is None:
                running.pending_final_status = status
                self._terminate(running)
            reader_task = running.reader_task

        if reader_task is not None and reader_task is not asyncio.current_task():
            await asyncio.shield(reader_task)

    @staticmethod
    def _terminate(running: RunningProcess) -> None:
        if running.process.returncode is not None:
            return
        try:
            running.process.terminate()
        except ProcessLookupError:
            return
        asyncio.create_task(ProcessManager._force_kill_later(running.process))

    # -- spawn / continue -----------------------------------------------

    async def _deliver_to_running(self, task_id: uuid.UUID, running: RunningProcess) -> bool:
        """Best-effort: forward the newest user message to a live process's stdin.

        Both bundled backends are documented (docs/SPEC.md) as single-shot
        per invocation (`claude -p` / `codex exec` exit after one turn), so
        in practice trigger() rarely observes a still-running process for the
        same task. Per SPEC.md step 1 we still attempt stdin delivery first;
        if the process isn't reading stdin this is a harmless no-op -- the
        message stays durably in Postgres and is delivered via --resume the
        next time trigger() spawns a fresh invocation for this task.
        """
        prompt = await self._latest_user_prompt(task_id)
        if (
            prompt is None
            or running.process.stdin is None
            or running.process.stdin.is_closing()
        ):
            return False
        try:
            running.process.stdin.write((prompt + "\n").encode("utf-8"))
            await running.process.stdin.drain()
            return True
        except (ConnectionResetError, BrokenPipeError, RuntimeError):
            logger.debug("stdin delivery failed for task %s; will resume next trigger", task_id)
            return False

    async def _reopen_for_follow_up(self, task_id: uuid.UUID) -> None:
        """Clear a terminal/attention state immediately before a follow-up spawn.

        The caller holds the task lifecycle lock. Keeping this transition in
        ProcessManager prevents route-level writes from racing cancel,
        complete, process exit, or a scheduled retry.
        """
        changed = False
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            if task.status in (
                TaskStatus.waiting_on_you,
                TaskStatus.done,
                TaskStatus.failed,
                TaskStatus.cancelled,
            ):
                task.status = TaskStatus.queued
                task.attention_reason = None
                task.completed_at = None
                await db.commit()
                changed = True
        if changed:
            await broadcast(
                task_id,
                {"type": "status", "status": TaskStatus.queued.value, "attention_reason": None},
            )

    async def _spawn(self, task_id: uuid.UUID, initial_prompt: str | None = None) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                logger.warning("trigger() called for unknown task %s", task_id)
                return
            if task.status in (TaskStatus.done, TaskStatus.cancelled):
                # A delayed retry or trigger may already have been waiting on
                # the lifecycle lock when the user completed/cancelled. Never
                # resurrect an explicit terminal state.
                return
            project = await self._load_project(db, task.project_id)
            if project is None:
                logger.warning("task %s references missing project %s", task_id, task.project_id)
                return

            adapter = _ADAPTERS[task.backend]
            bindings = await self._bindings_for(db, project, task)
            secrets = {s.key_name: decrypt_secret(s.encrypted_value) for s in project.secrets}

            if not bindings.primary_directory:
                message = "This project has no primary directory. Choose one in Project > Directories before running tasks."
                task.status = TaskStatus.failed
                task.completed_at = datetime.now(timezone.utc)
                db.add(Message(task_id=task_id, sender=MessageSender.system, content_text=message))
                await db.commit()
                await self._append_transcript(task_id, "system", message)
                await broadcast(task_id, {"type": "status", "status": TaskStatus.failed.value})
                return
            if not Path(bindings.primary_directory).is_dir():
                message = f"Primary directory is unavailable: {bindings.primary_directory}"
                task.status = TaskStatus.failed
                task.completed_at = datetime.now(timezone.utc)
                db.add(Message(task_id=task_id, sender=MessageSender.system, content_text=message))
                await db.commit()
                await self._append_transcript(task_id, "system", message)
                await broadcast(task_id, {"type": "status", "status": TaskStatus.failed.value})
                return

            # Capture the working-tree baseline once, before the task's first
            # subprocess can mutate files. A failed/unsupported capture stays
            # explicitly unknown (None) so PR delivery fails closed.
            if task.git_baseline_captured_at is None:
                from app.services.pr_delivery import capture_git_baseline

                baseline = await capture_git_baseline(bindings.primary_directory)
                if baseline is not None:
                    task.git_baseline_dirty_paths = baseline
                    task.git_baseline_captured_at = datetime.now(timezone.utc)

            backend_session = await _get_or_create_backend_session(db, task)
            resume_session_id = backend_session.session_id
            backend_session_path = _resolve_backend_session_path(backend_session.storage_path)

            if resume_session_id:
                prompt = await self._latest_user_prompt_db(db, task_id) or task.initial_prompt
                cmd = adapter.resume_command(
                    task, project, bindings, secrets, resume_session_id, prompt
                )
                await self._append_transcript(task_id, "user", prompt)
            else:
                prompt = initial_prompt or task.initial_prompt
                cmd = adapter.build_command(task, project, bindings, secrets, prompt)
                await self._append_transcript(task_id, "user", prompt)

            task.status = TaskStatus.running
            task.attention_reason = None
            task.completed_at = None
            if task.started_at is None:
                task.started_at = datetime.now(timezone.utc)
            previous = await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
            invocation = TaskInvocation(
                task_id=task_id,
                sequence=len(previous.scalars().all()) + 1,
                backend=task.backend,
                model=task.model or (
                    project.default_model if task.backend == project.default_backend else None
                ),
                thinking_level=task.thinking_level,
                status="running",
            )
            db.add(invocation)
            await db.commit()
            await db.refresh(invocation)
            invocation_id = invocation.id

        await broadcast(
            task_id,
            {"type": "status", "status": TaskStatus.running.value, "attention_reason": None},
        )

        runtime_env = {**os.environ, **secrets}
        runtime_temp_paths: list[Path] = list(_command_temp_paths(cmd.argv))
        if task.backend == AgentBackend.codex:
            if resume_session_id:
                repair_codex_rollout_path(resume_session_id)
            codex_home = create_codex_home_overlay(
                bindings.tool_rules, backend_session_path
            )
            runtime_env["CODEX_HOME"] = str(codex_home)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd.argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                env=runtime_env,
                cwd=bindings.primary_directory,
                limit=settings.runtime_stream_limit_bytes,
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            _cleanup_temp_paths(tuple(runtime_temp_paths))
            message = f"Unable to start {task.backend.value}: {exc}"
            async with SessionLocal() as db:
                failed_invocation = await db.get(TaskInvocation, invocation_id)
                if failed_invocation is not None:
                    failed_invocation.status = "failed"
                    failed_invocation.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    await db.refresh(failed_invocation)
                    await broadcast(
                        task_id,
                        {"type": "invocation", "invocation": _serialize_invocation(failed_invocation)},
                    )
            await self._persist_activity(task_id, invocation_id, "log", "Runtime failed to start", message)
            await self._persist_and_broadcast_message(task_id, MessageSender.system, message)
            await self._set_status(task_id, TaskStatus.failed, completed=True)
            return
        running = RunningProcess(
            process=process,
            invocation_id=invocation_id,
            backend=task.backend,
            temp_paths=tuple(runtime_temp_paths),
        )
        running.reader_task = asyncio.create_task(self._read_stdout(task_id, process, adapter, running))
        running.stderr_task = asyncio.create_task(
            self._read_stderr(task_id, invocation_id, process, running)
        )
        running.watchdog_task = asyncio.create_task(self._watchdog(task_id, running))
        self._running[task_id] = running

        # Start draining output before writing the prompt: large prompts and
        # eager CLI diagnostics can otherwise fill opposing pipes and deadlock.
        # Codex's documented `-` prompt source receives the complete prompt
        # before EOF; Claude keeps its prompt in argv and receives EOF only.
        if process.stdin is not None:
            if cmd.stdin_payload is not None:
                try:
                    process.stdin.write(cmd.stdin_payload.encode("utf-8"))
                    await process.stdin.drain()
                except (ConnectionResetError, BrokenPipeError, RuntimeError):
                    logger.warning("runtime closed stdin while receiving task %s", task_id)
            process.stdin.close()
        if bindings.approval_ids:
            async with SessionLocal() as db:
                approvals = (
                    await db.execute(
                        select(ToolApprovalRequest).where(
                            ToolApprovalRequest.id.in_(bindings.approval_ids)
                        )
                    )
                ).scalars().all()
                for approval in approvals:
                    approval.status = "consumed"
                await db.commit()
        await self._persist_activity(
            task_id,
            invocation_id,
            "invocation",
            f"{task.backend.value} invocation {invocation.sequence} started",
            metadata={"model": invocation.model, "thinking_level": invocation.thinking_level},
        )

    async def _load_project(self, db: AsyncSession, project_id: uuid.UUID) -> Project | None:
        result = await db.execute(
            select(Project)
            .options(
                selectinload(Project.directories),
                selectinload(Project.directories).selectinload(DirectoryBinding.directory),
                selectinload(Project.primary_directory),
                selectinload(Project.mcp_servers),
                selectinload(Project.tools),
                selectinload(Project.secrets),
            )
            .where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _bindings_for(db: AsyncSession, project: Project, task: Task) -> AdapterBindings:
        overrides = (
            await db.execute(
                select(ProjectCapabilityOverride).where(
                    ProjectCapabilityOverride.project_id == project.id
                )
            )
        ).scalars().all()
        override_map = {(row.resource_type, row.resource_id): row for row in overrides}

        global_mcp = (await db.execute(select(GlobalMcpServer))).scalars().all()
        mcp_servers: dict[str, dict] = {
            row.name: {**row.config, **(override_map.get(("mcp", row.id)).config_override if override_map.get(("mcp", row.id)) else {})}
            for row in global_mcp
            if row.enabled and (override_map.get(("mcp", row.id)) is None or override_map[("mcp", row.id)].enabled)
        }
        mcp_servers.update({m.name: m.config for m in project.mcp_servers})

        agents = (await db.execute(select(AgentProfile))).scalars().all()
        agent_profiles = {
            row.name: {
                "description": row.description or row.name,
                "prompt": row.system_prompt,
                **(row.config or {}),
            }
            for row in agents
            if row.enabled
            and row.backend == task.backend
            and (override_map.get(("agent", row.id)) is None or override_map[("agent", row.id)].enabled)
        }
        selected = next(
            (
                row
                for row in agents
                if row.id == task.agent_id
                and row.enabled
                and row.backend == task.backend
                and (
                    override_map.get(("agent", row.id)) is None
                    or override_map[("agent", row.id)].enabled
                )
            ),
            None,
        )

        skill_rows = (await db.execute(select(Skill))).scalars().all()
        skills = {
            row.name: row.instructions
            for row in skill_rows
            if row.enabled
            and (override_map.get(("skill", row.id)) is None or override_map[("skill", row.id)].enabled)
        }
        one_time_approvals = (
            await db.execute(
                select(ToolApprovalRequest).where(
                    ToolApprovalRequest.task_id == task.id,
                    ToolApprovalRequest.status == "approved_once",
                )
            )
        ).scalars().all()
        global_tools = (await db.execute(select(GlobalTool))).scalars().all()
        project_rules = [
            {
                **dict(tool.config or {}),
                **(
                    override_map[("tool", tool.id)].config_override
                    if override_map.get(("tool", tool.id))
                    else {}
                ),
            }
            for tool in global_tools
            if tool.enabled
            and (
                override_map.get(("tool", tool.id)) is None
                or override_map[("tool", tool.id)].enabled
            )
        ]
        project_rules.extend(dict(tool.config or {}) for tool in project.tools)
        project_rules.extend(dict(approval.permission_rule or {}) for approval in one_time_approvals)

        directory_paths = [
            binding.directory.path if binding.directory else binding.path
            for binding in project.directories
        ]
        primary_directory = project.primary_directory.path if project.primary_directory else None
        if primary_directory and primary_directory not in directory_paths:
            primary_directory = None
        if primary_directory:
            directory_paths = [primary_directory, *[path for path in directory_paths if path != primary_directory]]

        return AdapterBindings(
            primary_directory=primary_directory,
            directories=directory_paths,
            mcp_servers=mcp_servers,
            tool_rules=project_rules,
            agent_profiles=agent_profiles,
            skills=skills,
            selected_agent_prompt=selected.system_prompt if selected else None,
            approval_ids=tuple(approval.id for approval in one_time_approvals),
        )

    async def _latest_user_prompt(self, task_id: uuid.UUID) -> str | None:
        async with SessionLocal() as db:
            return await self._latest_user_prompt_db(db, task_id)

    @staticmethod
    async def _runtime_handoff_prompt_db(
        db: AsyncSession,
        task: Task,
        previous_backend: AgentBackend,
        next_backend: AgentBackend,
    ) -> str:
        result = await db.execute(
            select(Message).where(Message.task_id == task.id).order_by(Message.created_at)
        )
        messages = result.scalars().all()
        invocation_result = await db.execute(
            select(TaskInvocation)
            .where(TaskInvocation.task_id == task.id)
            .order_by(TaskInvocation.started_at)
        )
        invocations = invocation_result.scalars().all()
        rendered: list[str] = []
        for message in messages:
            content = (message.content_text or "").strip()
            canvas_snapshots = [
                item
                for item in (message.media or [])
                if isinstance(item, dict)
                and item.get("kind") == "magic_canvas"
                and isinstance(item.get("content"), str)
            ]
            if canvas_snapshots:
                content += (
                    "\n\n<magic_canvas_snapshots>"
                    + json.dumps(canvas_snapshots, ensure_ascii=False)
                    + "</magic_canvas_snapshots>"
                )
            if not content:
                continue
            label = "USER" if message.sender == MessageSender.user else "SYSTEM"
            if message.sender == MessageSender.agent:
                created_at = _timestamp(message.created_at)
                invocation = next(
                    (
                        item
                        for item in reversed(invocations)
                        if _timestamp(item.started_at) <= created_at
                        and (
                            item.completed_at is None
                            or created_at <= _timestamp(item.completed_at)
                        )
                    ),
                    None,
                )
                label = _backend_label(
                    invocation.backend if invocation is not None else previous_backend
                ).upper()
            rendered.append(f"[{label}]\n{content}")

        conversation = "\n\n".join(rendered)
        max_conversation_chars = 18_000
        if len(conversation) > max_conversation_chars:
            conversation = (
                "[Earlier conversation omitted to fit the runtime handoff.]\n\n"
                + conversation[-max_conversation_chars:]
            )
        brief = task.initial_prompt[:8_000]
        return (
            f"You are taking over an existing task from {_backend_label(previous_backend)}. "
            f"Continue it using {_backend_label(next_backend)} in the current project working "
            "directory. Inspect the current files before changing them; the working tree is the "
            "source of truth. Do not redo completed work.\n\n"
            f"ORIGINAL BRIEF\n{brief}\n\n"
            f"PRIOR CONVERSATION\n{conversation or '[No persisted conversation messages]'}\n\n"
            "Continue from the latest state and report what you do next."
        )

    @staticmethod
    async def _latest_user_prompt_db(db: AsyncSession, task_id: uuid.UUID) -> str | None:
        result = await db.execute(
            select(Message)
            .where(Message.task_id == task_id, Message.sender == MessageSender.user)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg = result.scalar_one_or_none()
        if msg is None:
            return None
        canvas = next(
            (
                item
                for item in (msg.media or [])
                if isinstance(item, dict)
                and item.get("kind") == "magic_canvas"
                and isinstance(item.get("content"), str)
            ),
            None,
        )
        if canvas is None:
            return msg.content_text
        canvas_payload = json.dumps(
            {
                "title": canvas.get("title"),
                "format": canvas.get("format"),
                "language": canvas.get("language"),
                "content": canvas["content"],
            },
            ensure_ascii=False,
        )
        return (
            f"{msg.content_text or ''}\n\n"
            "The following Magic Canvas snapshot is the current artifact and the absolute "
            "source of truth. Apply the user's requested changes to it instead of recreating "
            "the artifact from older conversation text. Return the complete updated artifact "
            "in one fenced block or as a complete Markdown document.\n"
            f"<magic_canvas_snapshot>{canvas_payload}</magic_canvas_snapshot>"
        )

    # -- stdout / stderr reading ------------------------------------------

    async def _read_stdout(
        self,
        task_id: uuid.UUID,
        process: asyncio.subprocess.Process,
        adapter: AgentBackendAdapter,
        running: RunningProcess,
    ) -> None:
        assert process.stdout is not None
        try:
            async for raw_line in process.stdout:
                running.last_activity_monotonic = time.monotonic()
                line = raw_line.decode("utf-8", errors="replace")
                try:
                    event = adapter.parse_line(line)
                except Exception:  # noqa: BLE001 - never let a bad line kill the reader
                    logger.exception("failed to parse backend output line for task %s", task_id)
                    continue
                if event is None:
                    continue
                running.received_event = True
                events = event if isinstance(event, list) else [event]
                for parsed in events:
                    await self._handle_event(task_id, parsed, running)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("stdout reader crashed for task %s", task_id)
            running.failure_reason = f"Runtime output could not be read: {exc}"
            await self._terminate_process_tree(process)
        finally:
            await self._on_process_exit(task_id, process, running)

    async def _read_stderr(
        self,
        task_id: uuid.UUID,
        invocation_id: uuid.UUID,
        process: asyncio.subprocess.Process,
        running: RunningProcess,
    ) -> None:
        assert process.stderr is not None
        try:
            async for chunk in process.stderr:
                running.last_activity_monotonic = time.monotonic()
                running.stderr_buf += chunk
                text = chunk.decode("utf-8", errors="replace").strip()
                if text:
                    await self._persist_activity(
                        task_id, invocation_id, "log", "Runtime log", text[-2000:]
                    )
                if len(running.stderr_buf) > _STDERR_TAIL_LIMIT:
                    del running.stderr_buf[: len(running.stderr_buf) - _STDERR_TAIL_LIMIT]
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("stderr reader crashed")

    async def _watchdog(self, task_id: uuid.UUID, running: RunningProcess) -> None:
        """Fail runtimes that never start, stop responding, or exceed their cap."""
        try:
            while running.process.returncode is None:
                await asyncio.sleep(settings.runtime_watchdog_interval_seconds)
                now = time.monotonic()
                elapsed = now - running.started_monotonic
                idle = now - running.last_activity_monotonic
                if (
                    not running.received_event
                    and elapsed >= settings.runtime_startup_timeout_seconds
                ):
                    reason = (
                        "Agent runtime startup timed out before producing a structured event "
                        f"({settings.runtime_startup_timeout_seconds:g}s)."
                    )
                elif idle >= settings.runtime_idle_timeout_seconds:
                    reason = (
                        "Agent runtime became unresponsive "
                        f"({settings.runtime_idle_timeout_seconds:g}s without output)."
                    )
                elif elapsed >= settings.runtime_max_seconds:
                    reason = (
                        "Agent runtime exceeded the maximum invocation duration "
                        f"({settings.runtime_max_seconds:g}s)."
                    )
                else:
                    continue
                running.failure_reason = reason
                logger.warning("%s Task: %s", reason, task_id)
                await self._terminate_process_tree(running.process)
                return
        except asyncio.CancelledError:
            raise

    async def _handle_event(self, task_id: uuid.UUID, event: ParsedEvent, running: RunningProcess) -> None:
        if isinstance(event, AgentText):
            await self._persist_and_broadcast_message(task_id, MessageSender.agent, event.text)
        elif isinstance(event, BlockingQuestion):
            running.blocking_question_hit = True
            await self._persist_and_broadcast_message(
                task_id, MessageSender.agent, event.text, is_blocking_question=True
            )
            await self._set_status(task_id, TaskStatus.waiting_on_you, attention_reason="blocking_question")
        elif isinstance(event, PermissionRequest):
            await self._handle_permission_request(task_id, running, event)
        elif isinstance(event, SessionId):
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                invocation = await db.get(TaskInvocation, running.invocation_id)
                backend_session = (
                    await db.execute(
                        select(TaskBackendSession).where(TaskBackendSession.task_id == task_id)
                    )
                ).scalar_one_or_none()
                if task is not None and task.session_id != event.session_id:
                    task.session_id = event.session_id
                if backend_session is not None:
                    backend_session.session_id = event.session_id
                if invocation is not None:
                    invocation.session_id = event.session_id
                await db.commit()
                if invocation is not None:
                    await broadcast(task_id, {"type": "invocation", "invocation": _serialize_invocation(invocation)})
        elif isinstance(event, Done):
            pass  # exit-code handling in _on_process_exit is authoritative
        elif isinstance(event, ErrorEvent):
            await self._persist_and_broadcast_message(task_id, MessageSender.system, event.message)
        elif isinstance(event, ActivityEvent):
            tool_use_id = str(event.metadata.get("tool_use_id") or event.metadata.get("item_id") or "")
            if event.kind == "tool_call" and tool_use_id:
                try:
                    tool_input = json.loads(event.content or "{}")
                except json.JSONDecodeError:
                    tool_input = {"command": event.content} if event.content else {}
                running.pending_tool_calls[tool_use_id] = (
                    event.title,
                    tool_input if isinstance(tool_input, dict) else {"input": tool_input},
                )
            await self._persist_activity(
                task_id,
                running.invocation_id,
                event.kind,
                event.title,
                event.content,
                event.metadata,
            )
            if (
                event.kind == "tool_result"
                and event.metadata.get("is_error")
                and _is_permission_failure(event.content)
            ):
                tool_name, tool_input = running.pending_tool_calls.get(
                    tool_use_id, ("Tool", {})
                )
                await self._handle_permission_request(
                    task_id,
                    running,
                    PermissionRequest(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        reason=event.content,
                    ),
                )
        elif isinstance(event, UsageEvent):
            async with SessionLocal() as db:
                invocation = await db.get(TaskInvocation, running.invocation_id)
                if invocation is not None:
                    invocation.input_tokens = event.input_tokens
                    invocation.output_tokens = event.output_tokens
                    invocation.cached_tokens = event.cached_tokens
                    await db.commit()
                    await broadcast(task_id, {"type": "invocation", "invocation": _serialize_invocation(invocation)})
                    await broadcast(task_id, {"type": "token_usage", "used": event.input_tokens + event.output_tokens, "limit": 0})

    async def _handle_permission_request(
        self,
        task_id: uuid.UUID,
        running: RunningProcess,
        request: PermissionRequest,
    ) -> None:
        if running.blocking_question_hit:
            return
        fingerprint = json.dumps(
            {"tool": request.tool_name, "input": request.tool_input}, sort_keys=True, default=str
        )
        if fingerprint in running.permission_requests:
            return
        running.permission_requests.add(fingerprint)
        running.blocking_question_hit = True
        rule = _suggest_permission_rule(running.backend, request.tool_name, request.tool_input)
        async with SessionLocal() as db:
            approval = ToolApprovalRequest(
                task_id=task_id,
                invocation_id=running.invocation_id,
                backend=running.backend,
                tool_name=request.tool_name,
                tool_input=request.tool_input,
                permission_rule=rule,
                reason=request.reason,
            )
            db.add(approval)
            await db.commit()
            await db.refresh(approval)
        await self._persist_activity(
            task_id,
            running.invocation_id,
            "permission",
            f"Permission required: {request.tool_name}",
            request.reason,
            {"approval_id": str(approval.id), "permission_rule": rule},
        )
        await self._persist_and_broadcast_message(
            task_id,
            MessageSender.agent,
            f"Permission required to run {request.tool_name}. Approve or deny the request below.",
            is_blocking_question=True,
        )
        await self._set_status(task_id, TaskStatus.waiting_on_you, attention_reason="tool_permission")
        await broadcast(
            task_id,
            {"type": "tool_approval", "approval": _serialize_tool_approval(approval)},
        )
        if running.process.returncode is None:
            await self._terminate_process_tree(running.process)

    async def _persist_and_broadcast_message(
        self,
        task_id: uuid.UUID,
        sender: MessageSender,
        text: str,
        is_blocking_question: bool = False,
    ) -> None:
        async with SessionLocal() as db:
            message = Message(
                task_id=task_id,
                sender=sender,
                content_text=text,
                is_blocking_question=is_blocking_question,
            )
            db.add(message)
            await db.commit()
            await db.refresh(message)
        await self._append_transcript(task_id, sender.value, text)
        await broadcast(task_id, {"type": "message", "message": _serialize_message(message)})

    # -- exit / retry handling ---------------------------------------------

    async def _broadcast_pr_hint(self, task_id: uuid.UUID) -> None:
        """Emit a read-only suggestion only when structured git state is eligible."""
        from app.services.pr_delivery import eligibility_hint

        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            project = await db.get(Project, task.project_id)
            if project is None:
                return
            hint = await eligibility_hint(db, task, project)
        if hint is not None:
            await broadcast(task_id, {"type": "pr_suggestion", **hint})

    async def _on_process_exit(
        self, task_id: uuid.UUID, process: asyncio.subprocess.Process, running: RunningProcess
    ) -> None:
        exit_code = await process.wait()
        if running.stderr_task is not None and running.stderr_task is not asyncio.current_task():
            try:
                await asyncio.wait_for(running.stderr_task, timeout=1)
            except asyncio.TimeoutError:
                running.stderr_task.cancel()
        if running.watchdog_task is not None and running.watchdog_task is not asyncio.current_task():
            running.watchdog_task.cancel()
        _cleanup_temp_paths(running.temp_paths)

        async with SessionLocal() as db:
            invocation = await db.get(TaskInvocation, running.invocation_id)
            if invocation is not None:
                invocation.status = (
                    "cancelled"
                    if (
                        running.cancel_requested
                        or running.restart_requested
                        or running.switch_requested
                        or running.pending_final_status == TaskStatus.cancelled
                    )
                    else "completed"
                    if (
                        (exit_code == 0 and running.failure_reason is None)
                        or running.pending_final_status == TaskStatus.done
                    )
                    else "failed"
                )
                invocation.completed_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(invocation)
        if invocation is not None:
            await broadcast(task_id, {"type": "invocation", "invocation": _serialize_invocation(invocation)})

        if running.restart_requested:
            # restart_from_beginning owns the next status transition and spawn.
            # This check intentionally precedes the lifecycle lock: restart
            # waits for this reader while holding that lock.
            if self._running.get(task_id) is running:
                self._running.pop(task_id, None)
            return

        if running.switch_requested:
            # switch_backend likewise owns the replacement invocation.
            if self._running.get(task_id) is running:
                self._running.pop(task_id, None)
            return

        # Everything below decides the Task's next status. Hold the per-task
        # lock so this can never interleave with a concurrent cancel()/
        # complete()/restart()/trigger() for the same task (e.g. a user
        # rapid-clicking between actions right as the process exits).
        async with self._lock_for(task_id):
            tracked = self._running.get(task_id)
            if tracked is not None and tracked is not running:
                # A newer invocation already owns the task. This stale reader
                # must not overwrite the newer invocation's state.
                return
            if tracked is running:
                self._running.pop(task_id, None)

            if running.pending_final_status is not None:
                # An explicit user action (cancel() or complete()) already
                # decided this task's fate; honor it over any exit-code-based
                # classification below.
                await self._set_status(task_id, running.pending_final_status, completed=True)
                return

            if running.blocking_question_hit:
                # Status is already waiting_on_you; the user's reply resumes it.
                return

            if exit_code == 0 and running.failure_reason is None:
                # NOTE(production-hardening): a clean process exit means the
                # CLI turn finished without error -- it does NOT mean the
                # user's request was actually delivered. There is no trusted,
                # structured signal here (a verified PR, a signed Canvas
                # artifact, etc.) that proves delivery, so we deliberately do
                # NOT auto-mark the task `done`. Hand control back to the
                # user instead; they close it out via
                # POST /tasks/{id}/complete (ProcessManager.complete()), or a
                # future trusted-artifact check could call complete() here
                # once such a signal exists and is verified. Never infer
                # completion from assistant prose.
                await self._set_status(
                    task_id, TaskStatus.waiting_on_you, attention_reason="awaiting_review"
                )
                await self._broadcast_pr_hint(task_id)
                return

            stderr_tail = bytes(running.stderr_buf).decode("utf-8", errors="replace")
            failure_class = (
                FailureClass.other
                if running.failure_reason is not None
                else retry.classify(exit_code, stderr_tail)
            )

            async with SessionLocal() as db:
                existing = await db.execute(
                    select(TaskRunAttempt).where(TaskRunAttempt.task_id == task_id)
                )
                attempt_number = len(existing.scalars().all()) + 1

            can_retry = (
                failure_class == FailureClass.transient and attempt_number <= settings.retry_max_attempts
            )
            backoff_seconds = retry.compute_backoff(attempt_number - 1) if can_retry else None
            error_message = (
                running.failure_reason
                or stderr_tail[-_STDERR_TAIL_LIMIT:]
                or f"exited with code {exit_code}"
            )

            async with SessionLocal() as db:
                run_attempt = TaskRunAttempt(
                    task_id=task_id,
                    attempt_number=attempt_number,
                    failure_class=failure_class,
                    error_message=error_message,
                    backoff_seconds=backoff_seconds,
                )
                db.add(run_attempt)
                sys_message = Message(
                    task_id=task_id,
                    sender=MessageSender.system,
                    content_text=f"Attempt {attempt_number} failed ({failure_class.value}): {error_message}",
                )
                db.add(sys_message)
                await db.commit()
                await db.refresh(run_attempt)
                await db.refresh(sys_message)

            await self._append_transcript(task_id, "system", sys_message.content_text or "")
            await broadcast(task_id, {"type": "run_attempt", "attempt": _serialize_run_attempt(run_attempt)})
            await broadcast(task_id, {"type": "message", "message": _serialize_message(sys_message)})

            if can_retry and backoff_seconds is not None:
                await self._set_status(task_id, TaskStatus.running)
                pending = asyncio.create_task(self._delayed_retry(task_id, backoff_seconds))
                self._pending_retries[task_id] = pending
            else:
                await self._set_status(task_id, TaskStatus.failed, completed=True)

    async def _delayed_retry(self, task_id: uuid.UUID, backoff_seconds: int) -> None:
        try:
            await asyncio.sleep(backoff_seconds)
        except asyncio.CancelledError:
            return
        self._pending_retries.pop(task_id, None)
        await self.trigger(task_id)

    # -- shared helpers -------------------------------------------------

    async def _set_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
        completed: bool = False,
        attention_reason: str | None = None,
    ) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            task.status = status
            # Only ever meaningful for waiting_on_you; every other status
            # passes None here, which clears a stale reason on the way out.
            task.attention_reason = attention_reason
            if completed:
                task.completed_at = datetime.now(timezone.utc)
            await db.commit()
        await broadcast(task_id, {"type": "status", "status": status.value, "attention_reason": attention_reason})

    async def _append_transcript(self, task_id: uuid.UUID, sender: str, text: str) -> None:
        settings.ensure_dirs()
        path = settings.transcripts_dir / f"{task_id}.jsonl"
        line = json.dumps(
            {"sender": sender, "text": text, "ts": datetime.now(timezone.utc).isoformat()}
        )
        await asyncio.to_thread(_append_line, path, line)

    async def _persist_activity(
        self,
        task_id: uuid.UUID,
        invocation_id: uuid.UUID | None,
        kind: str,
        title: str,
        content: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        async with SessionLocal() as db:
            event = TaskEvent(
                task_id=task_id,
                invocation_id=invocation_id,
                kind=kind,
                title=title,
                content=content,
                event_metadata=metadata or {},
            )
            db.add(event)
            await db.commit()
            await db.refresh(event)
        await broadcast(task_id, {"type": "activity", "event": _serialize_event(event)})


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _command_temp_paths(command: list[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for index, value in enumerate(command[:-1]):
        if value == "--mcp-config":
            paths.append(Path(command[index + 1]))
    return tuple(paths)


def _cleanup_temp_paths(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove temporary runtime config %s", path)


def _is_permission_failure(content: str | None) -> bool:
    if not content:
        return False
    normalized = content.lower()
    return any(
        phrase in normalized
        for phrase in (
            "requires approval",
            "require approval",
            "was blocked. for security",
            "permission denied",
            "not approved",
        )
    )


def _command_tokens(tool_input: dict) -> list[str]:
    command = tool_input.get("command") or tool_input.get("cmd")
    if isinstance(command, list):
        return [str(token) for token in command if str(token)]
    if not isinstance(command, str):
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _backend_label(backend: AgentBackend) -> str:
    return "Claude Code" if backend == AgentBackend.claude_code else "Codex"


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _suggest_permission_rule(
    backend: AgentBackend, tool_name: str, tool_input: dict
) -> dict:
    tokens = _command_tokens(tool_input)
    executable = Path(tokens[0]).name if tokens else ""
    if backend == AgentBackend.claude_code:
        claude_pattern = tool_name
        if tool_name.lower() == "bash" and executable:
            claude_pattern = f"Bash({executable} *)"
        return {
            "backend": "claude_code",
            "decision": "allow",
            "claude_pattern": claude_pattern,
            "codex_prefix": [],
        }
    return {
        "backend": "codex",
        "decision": "allow",
        "claude_pattern": None,
        "codex_prefix": [executable] if executable else [tool_name],
    }


def _serialize_message(message: Message) -> dict:
    return {
        "id": str(message.id),
        "task_id": str(message.task_id),
        "sender": message.sender.value,
        "content_text": message.content_text,
        "media": message.media,
        "is_blocking_question": message.is_blocking_question,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _serialize_tool_approval(approval: ToolApprovalRequest) -> dict:
    return {
        "id": str(approval.id),
        "task_id": str(approval.task_id),
        "invocation_id": str(approval.invocation_id) if approval.invocation_id else None,
        "backend": approval.backend.value,
        "tool_name": approval.tool_name,
        "tool_input": approval.tool_input,
        "permission_rule": approval.permission_rule,
        "reason": approval.reason,
        "status": approval.status,
        "resolution_scope": approval.resolution_scope,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
    }


def _serialize_run_attempt(attempt: TaskRunAttempt) -> dict:
    return {
        "id": str(attempt.id),
        "task_id": str(attempt.task_id),
        "attempt_number": attempt.attempt_number,
        "failure_class": attempt.failure_class.value if attempt.failure_class else None,
        "error_message": attempt.error_message,
        "backoff_seconds": attempt.backoff_seconds,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
    }


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
        "started_at": invocation.started_at.isoformat() if invocation.started_at else None,
        "completed_at": invocation.completed_at.isoformat() if invocation.completed_at else None,
    }


def _serialize_event(event: TaskEvent) -> dict:
    return {
        "id": str(event.id),
        "task_id": str(event.task_id),
        "invocation_id": str(event.invocation_id) if event.invocation_id else None,
        "kind": event.kind,
        "title": event.title,
        "content": event.content,
        "event_metadata": event.event_metadata,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


_structured_process_manager = ProcessManager()

# Imported after ProcessManager is defined so TerminalManager can reuse the
# mature binding/context resolution without a module import cycle.
from app.services.runtime_manager import RuntimeManager  # noqa: E402
from app.services.terminal_manager import TerminalManager  # noqa: E402

terminal_manager = TerminalManager(_structured_process_manager)
process_manager = RuntimeManager(_structured_process_manager, terminal_manager)
