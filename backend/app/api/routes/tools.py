"""ToolBinding endpoints, nested under /projects/{id}/tools."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ToolBinding
from app.db.session import get_db
from app.schemas.tool import ToolBindingCreate, ToolBindingRead

router = APIRouter(prefix="/projects", tags=["tools"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/tools")
async def list_tools(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(select(ToolBinding).where(ToolBinding.project_id == project_id))
    bindings = result.scalars().all()
    return {"items": [ToolBindingRead.model_validate(b) for b in bindings]}


@router.post("/{project_id}/tools", status_code=201, response_model=ToolBindingRead)
async def create_tool(
    project_id: uuid.UUID, body: ToolBindingCreate, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    binding = ToolBinding(project_id=project_id, **body.model_dump())
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return binding


@router.delete("/{project_id}/tools/{binding_id}", status_code=204)
async def delete_tool(
    project_id: uuid.UUID, binding_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    binding = await db.get(ToolBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="Tool binding not found")
    await db.delete(binding)
    await db.commit()
