"""Task + Message endpoints (see docs/SPEC.md #rest-api).

Mutating endpoints that kick off/continue agent work call into
`app.services.process_manager.process_manager`, a module owned by another
agent and not yet implemented at the time this file was written (see
docs/SPEC.md #integration-seams for the exact signatures relied on here).
"""
from __future__ import annotations

import uuid

import anyio

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import AgentProfile, ContextSnapshot, Message, MessageSender, Project, ProjectCapabilityOverride, RuntimeMode, Task, TaskEvent, TaskInvocation, TaskRunAttempt, TaskStatus
from app.db.session import get_db
from app.schemas.context_snapshot import ContextSnapshotRead
from app.schemas.activity import TaskEventRead, TaskInvocationRead
from app.schemas.message import MessageCreate, MessageRead
from app.schemas.run_attempt import TaskRunAttemptRead
from app.schemas.task import TaskBackendUpdate, TaskContextStrategyUpdate, TaskCreate, TaskModelsUpdate, TaskModelUpdate, TaskRead, TaskTagsUpdate, TaskThinkingUpdate
from app.services.process_manager import process_manager
from app.services import task_attachments, task_sources

router = APIRouter(tags=["tasks"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_task_or_404(db: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/projects/{project_id}/tasks")
async def list_tasks(
    project_id: uuid.UUID,
    status: TaskStatus | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(db, project_id)
    stmt = select(Task).where(Task.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    result = await db.execute(stmt.order_by(Task.created_at))
    tasks = result.scalars().all()
    return {"items": [TaskRead.model_validate(t) for t in tasks]}


@router.post("/projects/{project_id}/tasks", status_code=201, response_model=TaskRead)
async def create_task(project_id: uuid.UUID, body: TaskCreate, response: Response, db: AsyncSession = Depends(get_db)):
    if body.source_key is not None:
        async with task_sources.lock_for(project_id):
            return await _create_task(project_id, body, response, db)
    return await _create_task(project_id, body, response, db)


async def _create_task(project_id: uuid.UUID, body: TaskCreate, response: Response, db: AsyncSession):
    project = await _get_project_or_404(db, project_id)

    async def existing_source_task() -> Task | None:
        return await task_sources.find_task(db, project_id, body.source_key)

    async def update_existing(existing: Task) -> Task:
        await task_sources.bind_source(db, existing, body.source_key)
        if body.related_source_key:
            await task_sources.bind_source(db, existing, body.related_source_key)
        event = await task_sources.record_update(db, existing, body.source_event_key, body.source_update)
        await db.commit()
        await task_sources.dispatch_update(db, event)
        await db.refresh(existing)
        response.status_code = 200
        return existing

    if body.source_key is not None:
        existing = await existing_source_task()
        target = None
        if body.related_task_id is not None:
            target = await db.get(Task, body.related_task_id)
            if target is None or target.project_id != project_id:
                raise HTTPException(status_code=404, detail="Related task not found in this project")
        if body.related_source_key is not None:
            related = await task_sources.find_task(db, project_id, body.related_source_key)
            if related is None and target is None:
                raise HTTPException(status_code=404, detail="Related source task not found in this project")
            if related is not None and target is not None and related.id != target.id:
                raise HTTPException(status_code=409, detail="Related source belongs to another task")
            target = related or target
        if target is not None:
            if existing is not None and existing.id != target.id:
                raise HTTPException(status_code=409, detail="Sources already belong to different tasks")
            existing = target
        if existing is not None:
            return await update_existing(existing)
    from app.services import task_tags

    try:
        await task_tags.ensure_assignable_tags(db, project_id, body.tags)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    agent = await db.get(AgentProfile, body.agent_id) if body.agent_id else None
    if body.agent_id and agent is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    if agent is not None:
        override = (
            await db.execute(
                select(ProjectCapabilityOverride).where(
                    ProjectCapabilityOverride.project_id == project_id,
                    ProjectCapabilityOverride.resource_type == "agent",
                    ProjectCapabilityOverride.resource_id == agent.id,
                )
            )
        ).scalar_one_or_none()
        if not agent.enabled or (override is not None and not override.enabled):
            raise HTTPException(status_code=422, detail="Agent profile is disabled for this project")
    runtime_mode = body.runtime_mode or RuntimeMode(settings.default_task_runtime_mode)
    if runtime_mode == RuntimeMode.interactive and not settings.interactive_terminal_enabled:
        raise HTTPException(status_code=422, detail="Interactive terminal runtime is disabled")
    media = task_attachments.validate(body.media)
    task = Task(
        id=uuid.uuid4(),
        project_id=project_id,
        source_key=body.source_key,
        title=body.title,
        initial_prompt=body.initial_prompt + (f"\n\nLatest source update:\n{body.source_update}" if body.source_update else ""),
        media=media,
        status=TaskStatus.queued,
        backend=body.backend or project.default_backend,
        runtime_mode=runtime_mode,
        model=body.model or project.default_model,
        fallback_models=body.fallback_models,
        tags=body.tags,
        thinking_level=body.thinking_level or "medium",
        agent_id=body.agent_id,
        context_strategy=body.context_strategy or project.default_context_strategy,
    )
    db.add(task)
    claimed = False
    try:
        await db.flush()
        task_attachments.claim(media, task.id)
        claimed = True
        if body.source_key is not None:
            await task_sources.bind_source(db, task, body.source_key)
        event = await task_sources.record_update(db, task, body.source_event_key, body.source_update)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if claimed:
            task_attachments.release(media, task.id)
        if isinstance(exc, IntegrityError) and body.source_key is not None:
            existing = await existing_source_task()
            if existing is not None:
                return await update_existing(existing)
        raise
    await db.refresh(task)
    if event is None:
        await process_manager.trigger(task.id)
    else:
        await task_sources.dispatch_update(db, event, fresh=True)
    return task


@router.get("/tasks")
async def list_all_tasks(
    status: list[TaskStatus] | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return tasks across every project for the global command center."""
    stmt = select(Task)
    if status:
        stmt = stmt.where(Task.status.in_(status))
    result = await db.execute(stmt.order_by(Task.updated_at.desc(), Task.created_at.desc()))
    return {"items": [TaskRead.model_validate(task) for task in result.scalars().all()]}


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _get_task_or_404(db, task_id)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    media = list(task.media or [])
    if task.status in (TaskStatus.queued, TaskStatus.running, TaskStatus.waiting_on_you):
        await process_manager.cancel(task_id)
    await db.delete(task)
    await db.commit()
    task_attachments.delete(media, task_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    await process_manager.cancel(task_id)
    await db.refresh(task)
    return task


@router.post("/tasks/{task_id}/complete", response_model=TaskRead)
async def complete_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """"Mark conversation complete" is the only path that marks a task `done`.

    A clean agent process exit never does this on its own (see
    ProcessManager._on_process_exit) -- it hands the task back to the user as
    `waiting_on_you` instead. This endpoint is how the user explicitly signs
    off. Safe to call from any status: if a process is still running it's
    stopped first, then the task is finalized as `done`.

    """
    task = await _get_task_or_404(db, task_id)
    project = await _get_project_or_404(db, task.project_id)
    from app.services import pr_delivery

    gate = await pr_delivery.get_completion_gate(db, task, project)
    if not gate["satisfied"]:
        raise HTTPException(
            status_code=422,
            detail=gate["reason"] or "This project's PR policy must be satisfied first.",
        )
    await process_manager.complete(task_id)
    await db.refresh(task)
    return task


@router.post("/tasks/{task_id}/restart", response_model=TaskRead)
async def restart_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    await process_manager.restart_from_beginning(task.id)
    await db.refresh(task)
    return task


@router.post("/tasks/{task_id}/retry-now", response_model=TaskRead)
async def retry_now_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    await process_manager.retry_now(task_id)
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/backend", response_model=TaskRead)
async def update_task_backend(
    task_id: uuid.UUID, body: TaskBackendUpdate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    await process_manager.switch_backend(task.id, body.backend)
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/model", response_model=TaskRead)
async def update_task_model(
    task_id: uuid.UUID, body: TaskModelUpdate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    task.model = body.model
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/models", response_model=TaskRead)
async def update_task_models(
    task_id: uuid.UUID, body: TaskModelsUpdate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    if not body.models:
        raise HTTPException(status_code=422, detail="Select at least one model")
    task.model = body.models[0]
    task.fallback_models = body.models[1:]
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/thinking-level", response_model=TaskRead)
async def update_task_thinking(
    task_id: uuid.UUID, body: TaskThinkingUpdate, db: AsyncSession = Depends(get_db)
):
    if body.thinking_level not in {"low", "medium", "high", "xhigh", "max"}:
        raise HTTPException(status_code=422, detail="Unsupported thinking level")
    task = await _get_task_or_404(db, task_id)
    task.thinking_level = body.thinking_level
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/context-strategy", response_model=TaskRead)
async def update_task_context_strategy(
    task_id: uuid.UUID, body: TaskContextStrategyUpdate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    task.context_strategy = body.context_strategy
    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/tasks/{task_id}/tags", response_model=TaskRead)
async def update_task_tags(
    task_id: uuid.UUID, body: TaskTagsUpdate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    from app.services import task_tags

    current = list(task.tags or [])
    current_system = [tag for tag in current if tag.casefold() in task_tags.SYSTEM_TAG_NAMES]
    requested_system = [tag for tag in body.tags if tag.casefold() in task_tags.SYSTEM_TAG_NAMES]
    additions = {
        tag.casefold() for tag in requested_system
    } - {tag.casefold() for tag in current_system}
    if additions:
        raise HTTPException(status_code=422, detail="System workflow tags cannot be assigned manually")
    assignable = [tag for tag in body.tags if tag.casefold() not in task_tags.SYSTEM_TAG_NAMES]
    try:
        await task_tags.ensure_assignable_tags(db, task.project_id, assignable)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task.tags = [*assignable, *current_system]
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/tasks/{task_id}/compress-context", response_model=ContextSnapshotRead)
async def compress_task_context(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    from app.services.context_compression import compress

    await compress(task_id)
    result = await db.execute(
        select(ContextSnapshot)
        .where(ContextSnapshot.task_id == task_id)
        .order_by(ContextSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=500, detail="Context compression did not produce a snapshot")
    return snapshot


@router.get("/tasks/{task_id}/messages")
async def list_messages(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    result = await db.execute(
        select(Message).where(Message.task_id == task_id).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return {"items": [MessageRead.model_validate(m) for m in messages]}


@router.post("/tasks/{task_id}/messages", status_code=201, response_model=MessageRead)
async def create_message(
    task_id: uuid.UUID, body: MessageCreate, db: AsyncSession = Depends(get_db)
):
    task = await _get_task_or_404(db, task_id)
    message = Message(
        task_id=task_id,
        sender=MessageSender.user,
        content_text=body.content_text,
        media=body.media,
    )
    db.add(message)
    if any(
        isinstance(item, dict)
        and item.get("kind") == "magic_canvas"
        and bool(item.get("content"))
        for item in body.media
    ):
        from app.services.task_tags import add_system_tag

        await add_system_tag(db, task, "Canvas")
    await db.commit()
    await db.refresh(message)
    # ProcessManager owns the reopen + spawn transition under the same
    # per-task lock as cancel, complete, retry, and process exit.
    await process_manager.resume(task_id)
    return message


@router.get("/tasks/{task_id}/transcript")
async def get_transcript(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(db, task_id)
    result = await db.execute(
        select(ContextSnapshot)
        .where(ContextSnapshot.task_id == task_id)
        .order_by(ContextSnapshot.created_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No transcript available for this task")
    path = snapshot.raw_transcript_path
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"Transcript file not found: {exc}") from exc
    return {"task_id": str(task.id), "transcript": text}


@router.get("/tasks/{task_id}/run-attempts")
async def list_run_attempts(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    result = await db.execute(
        select(TaskRunAttempt)
        .where(TaskRunAttempt.task_id == task_id)
        .order_by(TaskRunAttempt.created_at)
    )
    attempts = result.scalars().all()
    return {"items": [TaskRunAttemptRead.model_validate(a) for a in attempts]}


@router.get("/tasks/{task_id}/invocations")
async def list_invocations(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    result = await db.execute(
        select(TaskInvocation)
        .where(TaskInvocation.task_id == task_id)
        .order_by(TaskInvocation.started_at)
    )
    return {"items": [TaskInvocationRead.model_validate(row) for row in result.scalars().all()]}


@router.get("/tasks/{task_id}/events")
async def list_task_events(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_or_404(db, task_id)
    result = await db.execute(
        select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.created_at)
    )
    return {"items": [TaskEventRead.model_validate(row) for row in result.scalars().all()]}


@router.get("/tasks/{task_id}/terminal-history")
async def terminal_history(
    task_id: uuid.UUID,
    cursor: str = Query("0:0", max_length=64),
    db: AsyncSession = Depends(get_db),
):
    from app.services.terminal_history import history_paths, read_page

    task = await _get_task_or_404(db, task_id)
    result = await db.execute(select(TaskInvocation.session_id).where(
        TaskInvocation.task_id == task_id,
        TaskInvocation.session_id.is_not(None),
    ))
    ids = list(result.scalars().all())
    if task.session_id:
        ids.append(task.session_id)
    try:
        paths = await anyio.to_thread.run_sync(history_paths, task_id, ids)
        return await anyio.to_thread.run_sync(read_page, paths, cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Session history could not be read; try again") from exc
