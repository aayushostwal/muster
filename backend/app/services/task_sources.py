"""Source aliases and one durable conversation message per external update."""
import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import JiraIssueLink, Message, MessageSender, Task, TaskSourceEvent, TaskSourceLink
from app.services.process_manager import process_manager

_project_locks: dict[uuid.UUID, asyncio.Lock] = {}


def lock_for(project_id: uuid.UUID) -> asyncio.Lock:
    # The local runtime manager owns dispatch in this process. Serialize intake
    # through commit + dispatch; DB uniqueness additionally protects source rows.
    return _project_locks.setdefault(project_id, asyncio.Lock())


async def find_task(db, project_id: uuid.UUID, source_key: str) -> Task | None:
    task = (await db.execute(select(Task).join(TaskSourceLink, TaskSourceLink.task_id == Task.id).where(
        TaskSourceLink.project_id == project_id, TaskSourceLink.source_key == source_key,
    ))).scalar_one_or_none()
    if task is not None:
        return task
    task = (await db.execute(select(Task).where(Task.project_id == project_id, Task.source_key == source_key))).scalar_one_or_none()
    if task is not None or not source_key.startswith("jira:"):
        return task
    # Reuse historical tasks created by the built-in Jira integration too.
    identity = source_key.removeprefix("jira:")
    return (await db.execute(select(Task).join(JiraIssueLink, JiraIssueLink.task_id == Task.id).where(
        Task.project_id == project_id,
        (JiraIssueLink.issue_id == identity) | (JiraIssueLink.issue_key == identity),
    ))).scalar_one_or_none()


async def bind_source(db, task: Task, source_key: str) -> None:
    linked = await find_task(db, task.project_id, source_key)
    if linked is not None and linked.id != task.id:
        raise HTTPException(status_code=409, detail="Source is already linked to another task")
    alias = (await db.execute(select(TaskSourceLink).where(
        TaskSourceLink.project_id == task.project_id, TaskSourceLink.source_key == source_key,
    ))).scalar_one_or_none()
    if alias is None:
        db.add(TaskSourceLink(project_id=task.project_id, task_id=task.id, source_key=source_key))


async def record_update(db, task: Task, event_key: str | None, content: str | None) -> TaskSourceEvent | None:
    if event_key is None:
        return None
    event = (await db.execute(select(TaskSourceEvent).where(
        TaskSourceEvent.task_id == task.id, TaskSourceEvent.event_key == event_key,
    ))).scalar_one_or_none()
    if event is not None:
        return event
    message = Message(task_id=task.id, sender=MessageSender.user, content_text=content, created_at=datetime.now(timezone.utc))
    db.add(message)
    await db.flush()
    event = TaskSourceEvent(task_id=task.id, event_key=event_key, message_id=message.id)
    db.add(event)
    return event


async def dispatch_update(db, event: TaskSourceEvent | None, *, fresh: bool = False) -> None:
    if event is None or event.status == "delivered":
        return
    if fresh:
        await process_manager.trigger(event.task_id)
    else:
        await process_manager.resume(event.task_id)
    event.status = "delivered"
    await db.commit()
