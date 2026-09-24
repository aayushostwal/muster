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
import shlex
import shutil
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
    Skill,
    Task,
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
from app.services.agent_backends.codex import CodexAdapter, create_codex_home_overlay

logger = logging.getLogger(__name__)

_ADAPTERS: dict[AgentBackend, AgentBackendAdapter] = {
    AgentBackend.claude_code: ClaudeCodeAdapter(),
    AgentBackend.codex: CodexAdapter(),
}

_STDERR_TAIL_LIMIT = 4000
_FORCE_KILL_GRACE = 5.0


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
    pending_tool_calls: dict[str, tuple[str, dict]] = field(default_factory=dict)
    permission_requests: set[str] = field(default_factory=set)


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
        async with self._lock_for(task_id):
            running = self._running.get(task_id)
            if running is not None and running.process.returncode is None:
                await self._deliver_to_running(task_id, running)
                return
            await self._spawn(task_id)

    async def cancel(self, task_id: uuid.UUID) -> None:
        pending = self._pending_retries.pop(task_id, None)
        if pending is not None:
            pending.cancel()

        running = self._running.get(task_id)
        if running is not None:
            # Mark cancellation intent; _on_process_exit (driven by the
            # stdout reader's natural EOF once the process dies) reads this
            # flag and finalizes the Task as `cancelled` instead of running
            # its normal done/failed/retry classification.
            running.cancel_requested = True
            if running.process.returncode is None:
                try:
                    running.process.terminate()
                except ProcessLookupError:
                    pass
                asyncio.create_task(self._force_kill_later(running.process))
            return

        # No live process (task already finished, or is waiting_on_you /
        # between retries): finalize directly.
        await self._set_status(task_id, TaskStatus.cancelled, completed=True)

    async def retry_now(self, task_id: uuid.UUID) -> None:
        pending = self._pending_retries.pop(task_id, None)
        if pending is not None:
            pending.cancel()
        await self.trigger(task_id)

    async def resume_after_approval(self, task_id: uuid.UUID) -> None:
        """Stop an approval-blocked CLI turn, then resume it with the new rule set."""
        running = self._running.get(task_id)
        if running is not None and running.process.returncode is None:
            running.process.terminate()
            try:
                await asyncio.wait_for(running.process.wait(), timeout=_FORCE_KILL_GRACE)
            except asyncio.TimeoutError:
                running.process.kill()
                await running.process.wait()
            if running.reader_task is not None and running.reader_task is not asyncio.current_task():
                await running.reader_task
        await self.trigger(task_id)

    @staticmethod
    async def _force_kill_later(process: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=_FORCE_KILL_GRACE)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    # -- spawn / continue -----------------------------------------------

    async def _deliver_to_running(self, task_id: uuid.UUID, running: RunningProcess) -> None:
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
        if prompt is None or running.process.stdin is None:
            return
        try:
            running.process.stdin.write((prompt + "\n").encode("utf-8"))
            await running.process.stdin.drain()
        except (ConnectionResetError, BrokenPipeError, RuntimeError):
            logger.debug("stdin delivery failed for task %s; will resume next trigger", task_id)

    async def _spawn(self, task_id: uuid.UUID) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                logger.warning("trigger() called for unknown task %s", task_id)
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

            if task.session_id:
                prompt = await self._latest_user_prompt_db(db, task_id) or task.initial_prompt
                cmd = adapter.resume_command(task, project, bindings, secrets, task.session_id, prompt)
                await self._append_transcript(task_id, "user", prompt)
            else:
                cmd = adapter.build_command(task, project, bindings, secrets)
                await self._append_transcript(task_id, "user", task.initial_prompt)

            task.status = TaskStatus.running
            if task.started_at is None:
                task.started_at = datetime.now(timezone.utc)
            previous = await db.execute(select(TaskInvocation).where(TaskInvocation.task_id == task_id))
            invocation = TaskInvocation(
                task_id=task_id,
                sequence=len(previous.scalars().all()) + 1,
                backend=task.backend,
                model=task.model or project.default_model,
                thinking_level=task.thinking_level,
                status="running",
            )
            db.add(invocation)
            await db.commit()
            await db.refresh(invocation)
            invocation_id = invocation.id

        await broadcast(task_id, {"type": "status", "status": TaskStatus.running.value})

        runtime_env = {**os.environ, **secrets}
        runtime_temp_paths: list[Path] = list(_command_temp_paths(cmd))
        if task.backend == AgentBackend.codex:
            codex_home = create_codex_home_overlay(bindings.tool_rules)
            if codex_home is not None:
                runtime_env["CODEX_HOME"] = str(codex_home)
                runtime_temp_paths.append(codex_home)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                env=runtime_env,
                cwd=bindings.primary_directory,
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
        # The prompt is always passed via -p / the resumed invocation's
        # argv, never stdin, and both CLIs are single-shot per invocation
        # (see SPEC.md). An open-but-silent stdin pipe makes `claude` stall
        # for several seconds waiting for input that will never arrive
        # (observed: "Warning: no stdin data received in 3s..."), so close
        # it immediately. `_deliver_to_running`'s best-effort stdin write
        # becomes a no-op once this runs, which matches its own docstring.
        if process.stdin is not None:
            process.stdin.close()

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
        self._running[task_id] = running
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
                line = raw_line.decode("utf-8", errors="replace")
                try:
                    event = adapter.parse_line(line)
                except Exception:  # noqa: BLE001 - never let a bad line kill the reader
                    logger.exception("failed to parse backend output line for task %s", task_id)
                    continue
                if event is None:
                    continue
                events = event if isinstance(event, list) else [event]
                for parsed in events:
                    await self._handle_event(task_id, parsed, running)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("stdout reader crashed for task %s", task_id)
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

    async def _handle_event(self, task_id: uuid.UUID, event: ParsedEvent, running: RunningProcess) -> None:
        if isinstance(event, AgentText):
            await self._persist_and_broadcast_message(task_id, MessageSender.agent, event.text)
        elif isinstance(event, BlockingQuestion):
            running.blocking_question_hit = True
            await self._persist_and_broadcast_message(
                task_id, MessageSender.agent, event.text, is_blocking_question=True
            )
            await self._set_status(task_id, TaskStatus.waiting_on_you)
        elif isinstance(event, PermissionRequest):
            await self._handle_permission_request(task_id, running, event)
        elif isinstance(event, SessionId):
            async with SessionLocal() as db:
                task = await db.get(Task, task_id)
                invocation = await db.get(TaskInvocation, running.invocation_id)
                if task is not None and task.session_id != event.session_id:
                    task.session_id = event.session_id
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
        await self._set_status(task_id, TaskStatus.waiting_on_you)
        await broadcast(
            task_id,
            {"type": "tool_approval", "approval": _serialize_tool_approval(approval)},
        )
        if running.process.returncode is None:
            running.process.terminate()

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

    async def _on_process_exit(
        self, task_id: uuid.UUID, process: asyncio.subprocess.Process, running: RunningProcess
    ) -> None:
        exit_code = await process.wait()
        if running.stderr_task is not None:
            running.stderr_task.cancel()
        _cleanup_temp_paths(running.temp_paths)
        self._running.pop(task_id, None)

        async with SessionLocal() as db:
            invocation = await db.get(TaskInvocation, running.invocation_id)
            if invocation is not None:
                invocation.status = "cancelled" if running.cancel_requested else "completed" if exit_code == 0 else "failed"
                invocation.completed_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(invocation)
        if invocation is not None:
            await broadcast(task_id, {"type": "invocation", "invocation": _serialize_invocation(invocation)})

        if running.cancel_requested:
            await self._set_status(task_id, TaskStatus.cancelled, completed=True)
            return

        if running.blocking_question_hit:
            # Status is already waiting_on_you; the user's reply resumes it.
            return

        if exit_code == 0:
            await self._set_status(task_id, TaskStatus.done, completed=True)
            return

        stderr_tail = bytes(running.stderr_buf).decode("utf-8", errors="replace")
        failure_class = retry.classify(exit_code, stderr_tail)

        async with SessionLocal() as db:
            existing = await db.execute(
                select(TaskRunAttempt).where(TaskRunAttempt.task_id == task_id)
            )
            attempt_number = len(existing.scalars().all()) + 1

        can_retry = (
            failure_class == FailureClass.transient and attempt_number <= settings.retry_max_attempts
        )
        backoff_seconds = retry.compute_backoff(attempt_number - 1) if can_retry else None
        error_message = stderr_tail[-_STDERR_TAIL_LIMIT:] or f"exited with code {exit_code}"

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

    async def _set_status(self, task_id: uuid.UUID, status: TaskStatus, completed: bool = False) -> None:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            task.status = status
            if completed:
                task.completed_at = datetime.now(timezone.utc)
            await db.commit()
        await broadcast(task_id, {"type": "status", "status": status.value})

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


process_manager = ProcessManager()
