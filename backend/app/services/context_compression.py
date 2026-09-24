"""Context compression: summarize older Messages into a ContextSnapshot.

See docs/SPEC.md "Context compression". Keeps the most recent 10 Messages
verbatim and produces a one-shot summary of everything older via the task's
own backend CLI. This is a direct, minimal CLI invocation rather than
AgentBackendAdapter.build_command/resume_command, since those are shaped
around continuing a Task's own multi-turn conversation (and mutate
Task.session_id), not an ad-hoc, out-of-band summarization prompt.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from app.config import settings
from app.db.models import AgentBackend, ContextSnapshot, Message, Task
from app.db.session import SessionLocal
from app.services.agent_backends.base import AgentText, BackendCommand
from app.services.agent_backends.claude_code import ClaudeCodeAdapter
from app.services.agent_backends.codex import CodexAdapter

_KEEP_VERBATIM = 10

_ADAPTERS = {
    AgentBackend.claude_code: ClaudeCodeAdapter(),
    AgentBackend.codex: CodexAdapter(),
}


def _summarize_command(backend: AgentBackend, prompt: str) -> BackendCommand:
    if backend == AgentBackend.claude_code:
        return BackendCommand(
            argv=[settings.claude_code_bin, "-p", prompt, "--output-format", "stream-json"]
        )
    return BackendCommand(
        argv=[settings.codex_bin, "exec", "-", "--json"], stdin_payload=prompt
    )


async def _run_one_shot(backend: AgentBackend, prompt: str) -> str:
    """Run a single non-interactive summarization prompt against the task's
    own backend CLI and concatenate any AgentText chunks it streams back."""
    adapter = _ADAPTERS[backend]
    cmd = _summarize_command(backend, prompt)
    process = await asyncio.create_subprocess_exec(
        *cmd.argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=settings.runtime_stream_limit_bytes,
    )
    if process.stdin is not None:
        if cmd.stdin_payload is not None:
            try:
                process.stdin.write(cmd.stdin_payload.encode("utf-8"))
            except (ConnectionResetError, BrokenPipeError, RuntimeError):
                pass
        process.stdin.close()
    chunks: list[str] = []
    assert process.stdout is not None
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8", errors="replace")
        event = adapter.parse_line(line)
        if isinstance(event, AgentText):
            chunks.append(event.text)
    await process.wait()
    return "".join(chunks).strip()


def _format_message(message: Message) -> str:
    return f"[{message.sender.value}] {message.content_text or ''}"


async def compress(task_id: uuid.UUID) -> ContextSnapshot:
    """Create and persist a ContextSnapshot for `task_id`.

    Older Messages (all but the most recent _KEEP_VERBATIM) are summarized;
    the raw transcript on disk (written incrementally by process_manager) is
    never deleted -- the snapshot just points at it.
    """
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None:
            raise ValueError(f"unknown task {task_id}")

        result = await db.execute(
            select(Message).where(Message.task_id == task_id).order_by(Message.created_at)
        )
        messages = list(result.scalars().all())

        older = messages[:-_KEEP_VERBATIM] if len(messages) > _KEEP_VERBATIM else []

        if older:
            transcript_excerpt = "\n".join(_format_message(m) for m in older)
            prompt = f"Summarize this conversation: {transcript_excerpt}"
            summary_text = await _run_one_shot(task.backend, prompt)
            if not summary_text:
                summary_text = f"[{len(older)} earlier messages; summarization produced no output]"
        else:
            summary_text = "(nothing to summarize yet)"

        raw_transcript_path = str(settings.transcripts_dir / f"{task_id}.jsonl")

        snapshot = ContextSnapshot(
            task_id=task_id,
            summary_text=summary_text,
            raw_transcript_path=raw_transcript_path,
            token_count=None,
        )
        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)
        return snapshot
