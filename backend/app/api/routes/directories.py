"""DirectoryBinding endpoints, nested under /projects/{id}/directories."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AccessScope, DirectoryBinding, DirectoryResource, Project
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
        select(DirectoryBinding)
        .options(selectinload(DirectoryBinding.directory))
        .where(DirectoryBinding.project_id == project_id)
    )
    bindings = result.scalars().all()
    return {
        "items": [
            DirectoryBindingRead(
                id=b.id,
                project_id=b.project_id,
                directory_id=b.directory_id,
                path=b.directory.path if b.directory else b.path,
                name=b.directory.name if b.directory else None,
                access_scope=b.access_scope,
                created_at=b.created_at,
            )
            for b in bindings
        ]
    }


@router.post("/{project_id}/directories", status_code=201, response_model=DirectoryBindingRead)
async def create_directory(
    project_id: uuid.UUID, body: DirectoryBindingCreate, db: AsyncSession = Depends(get_db)
):
    project = await _get_project_or_404(db, project_id)
    directory = await db.get(DirectoryResource, body.directory_id)
    if directory is None:
        raise HTTPException(status_code=404, detail="Global directory not found")
    binding = DirectoryBinding(
        project_id=project_id,
        directory_id=directory.id,
        path=directory.path,
        access_scope=body.access_scope,
    )
    db.add(binding)
    if project.primary_directory_id is None and body.access_scope == AccessScope.read_write:
        project.primary_directory_id = directory.id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Directory is already bound to this project") from exc
    await db.refresh(binding)
    return DirectoryBindingRead(
        id=binding.id,
        project_id=binding.project_id,
        directory_id=binding.directory_id,
        path=directory.path,
        name=directory.name,
        access_scope=binding.access_scope,
        created_at=binding.created_at,
    )


@router.delete("/{project_id}/directories/{binding_id}", status_code=204)
async def delete_directory(
    project_id: uuid.UUID, binding_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    binding = await db.get(DirectoryBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="Directory binding not found")
    project = await _get_project_or_404(db, project_id)
    if binding.directory_id == project.primary_directory_id:
        raise HTTPException(
            status_code=409,
            detail="Choose another primary directory before removing this one",
        )
    await db.delete(binding)
    await db.commit()
