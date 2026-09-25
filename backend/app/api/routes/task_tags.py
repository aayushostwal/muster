from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectTaskTag, Task
from app.db.session import get_db
from app.schemas.task_tag import ProjectTaskTagCreate, ProjectTaskTagRead, ProjectTaskTagUpdate
from app.services import task_tags

router = APIRouter(prefix="/projects/{project_id}/task-tags", tags=["task-tags"])


async def _project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("")
async def list_task_tags(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _project(db, project_id)
    items = await task_tags.ensure_catalog(db, project_id)
    await db.commit()
    return {"items": [ProjectTaskTagRead.model_validate(item) for item in items]}


@router.post("", status_code=201, response_model=ProjectTaskTagRead)
async def create_task_tag(
    project_id: uuid.UUID, body: ProjectTaskTagCreate, db: AsyncSession = Depends(get_db)
):
    await _project(db, project_id)
    await task_tags.ensure_catalog(db, project_id)
    normalized = body.name.casefold()
    existing = (
        await db.execute(
            select(ProjectTaskTag).where(
                ProjectTaskTag.project_id == project_id,
                ProjectTaskTag.normalized_name == normalized,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A tag with this name already exists")
    item = ProjectTaskTag(
        project_id=project_id,
        name=body.name,
        normalized_name=normalized,
        kind="custom",
        color=body.color,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{tag_id}", response_model=ProjectTaskTagRead)
async def update_task_tag(
    project_id: uuid.UUID,
    tag_id: uuid.UUID,
    body: ProjectTaskTagUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _project(db, project_id)
    item = await db.get(ProjectTaskTag, tag_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Tag not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != item.name:
        if item.kind == "system":
            raise HTTPException(status_code=422, detail="System workflow tags cannot be renamed")
        new_name = changes["name"]
        normalized = new_name.casefold()
        collision = (
            await db.execute(
                select(ProjectTaskTag).where(
                    ProjectTaskTag.project_id == project_id,
                    ProjectTaskTag.normalized_name == normalized,
                    ProjectTaskTag.id != tag_id,
                )
            )
        ).scalar_one_or_none()
        if collision is not None:
            raise HTTPException(status_code=409, detail="A tag with this name already exists")
        old_normalized = item.normalized_name
        tasks = (
            await db.execute(select(Task).where(Task.project_id == project_id))
        ).scalars()
        for task in tasks:
            task.tags = [new_name if tag.casefold() == old_normalized else tag for tag in (task.tags or [])]
        item.name = new_name
        item.normalized_name = normalized
    if "color" in changes:
        item.color = changes["color"]
    await db.commit()
    await db.refresh(item)
    return item
