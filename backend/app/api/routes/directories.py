"""DirectoryBinding endpoints, nested under /projects/{id}/directories."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DirectoryBinding, Project
from app.db.session import get_db
from app.schemas.directory import DirectoryBindingCreate, DirectoryBindingRead

router = APIRouter(prefix="/projects", tags=["directories"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/directories")
async def list_directories(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(
        select(DirectoryBinding).where(DirectoryBinding.project_id == project_id)
    )
    bindings = result.scalars().all()
    return {"items": [DirectoryBindingRead.model_validate(b) for b in bindings]}


@router.post("/{project_id}/directories", status_code=201, response_model=DirectoryBindingRead)
async def create_directory(
    project_id: uuid.UUID, body: DirectoryBindingCreate, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    binding = DirectoryBinding(project_id=project_id, **body.model_dump())
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return binding


@router.delete("/{project_id}/directories/{binding_id}", status_code=204)
async def delete_directory(
    project_id: uuid.UUID, binding_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    binding = await db.get(DirectoryBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="Directory binding not found")
    await db.delete(binding)
    await db.commit()
