"""McpBinding endpoints, nested under /projects/{id}/mcp-servers."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import McpBinding, Project
from app.db.session import get_db
from app.schemas.mcp_server import McpBindingCreate, McpBindingRead, McpBindingUpdate

router = APIRouter(prefix="/projects", tags=["mcp-servers"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/mcp-servers")
async def list_mcp_servers(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(select(McpBinding).where(McpBinding.project_id == project_id))
    bindings = result.scalars().all()
    return {"items": [McpBindingRead.model_validate(b) for b in bindings]}


@router.post("/{project_id}/mcp-servers", status_code=201, response_model=McpBindingRead)
async def create_mcp_server(
    project_id: uuid.UUID, body: McpBindingCreate, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    binding = McpBinding(
        project_id=project_id, name=body.name, config=body.config.model_dump()
    )
    db.add(binding)
    await db.commit()
    await db.refresh(binding)
    return binding


@router.patch("/{project_id}/mcp-servers/{binding_id}", response_model=McpBindingRead)
async def update_mcp_server(
    project_id: uuid.UUID,
    binding_id: uuid.UUID,
    body: McpBindingUpdate,
    db: AsyncSession = Depends(get_db),
):
    binding = await db.get(McpBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="MCP server binding not found")
    data = body.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        data["config"] = body.config.model_dump()
    for field, value in data.items():
        setattr(binding, field, value)
    await db.commit()
    await db.refresh(binding)
    return binding


@router.delete("/{project_id}/mcp-servers/{binding_id}", status_code=204)
async def delete_mcp_server(
    project_id: uuid.UUID, binding_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    binding = await db.get(McpBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=404, detail="MCP server binding not found")
    await db.delete(binding)
    await db.commit()
