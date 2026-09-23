"""Project CRUD endpoints (see docs/SPEC.md #rest-api)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccessScope, DirectoryBinding, DirectoryResource, Project
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
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).order_by(Project.created_at))
    projects = result.scalars().all()
    return {"items": [ProjectRead.model_validate(p) for p in projects]}


@router.post("", status_code=201, response_model=ProjectRead)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    primary_directory_id = data.pop("primary_directory_id")
    directory = None
    if primary_directory_id is not None:
        directory = await db.get(DirectoryResource, primary_directory_id)
        if directory is None:
            raise HTTPException(status_code=404, detail="Primary directory not found")
    project = Project(**data, primary_directory_id=primary_directory_id)
    db.add(project)
    await db.flush()
    if directory is not None:
        db.add(
            DirectoryBinding(
                project_id=project.id,
                directory_id=directory.id,
                path=directory.path,
                access_scope=AccessScope.read_write,
            )
        )
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
    changes = body.model_dump(exclude_unset=True)
    if "primary_directory_id" in changes and changes["primary_directory_id"] is not None:
        directory_id = changes["primary_directory_id"]
        binding = (
            await db.execute(
                select(DirectoryBinding).where(
                    DirectoryBinding.project_id == project_id,
                    DirectoryBinding.directory_id == directory_id,
                )
            )
        ).scalar_one_or_none()
        if binding is None:
            raise HTTPException(
                status_code=422,
                detail="The primary directory must already be granted to this project",
            )
        if binding.access_scope != AccessScope.read_write:
            raise HTTPException(
                status_code=422,
                detail="The primary directory requires read and write access",
            )
    for field, value in changes.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)
    await db.delete(project)
    await db.commit()
