"""Project CRUD + archive/unarchive endpoints (see docs/SPEC.md #rest-api)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.db.session import get_db
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("")
async def list_projects(
    archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Project)
    if not archived:
        stmt = stmt.where(Project.archived.is_(False))
    result = await db.execute(stmt.order_by(Project.created_at))
    projects = result.scalars().all()
    return {"items": [ProjectRead.model_validate(p) for p in projects]}


@router.post("", status_code=201, response_model=ProjectRead)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(**body.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _get_project_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, db: AsyncSession = Depends(get_db)
):
    project = await _get_project_or_404(db, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)
    project.archived = True
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
async def unarchive_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)
    project.archived = False
    await db.commit()
    await db.refresh(project)
    return project
