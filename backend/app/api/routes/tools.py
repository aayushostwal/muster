"""ToolBinding endpoints, nested under /projects/{id}/tools."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Message,
    MessageSender,
    Project,
    Task,
    TaskStatus,
    ToolApprovalRequest,
    ToolBinding,
)
from app.db.session import get_db
from app.schemas.tool import ToolApprovalRead, ToolApprovalResolve, ToolBindingCreate, ToolBindingRead
from app.services.process_manager import process_manager

router = APIRouter(prefix="/projects", tags=["tools"])
task_router = APIRouter(prefix="/tasks", tags=["tool-approvals"])


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
    binding = ToolBinding(
        project_id=project_id,
        name=body.name,
        config=body.config.model_dump(),
    )
    db.add(binding)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A tool rule with this name already exists") from exc
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


@task_router.get("/{task_id}/tool-approvals")
async def list_tool_approvals(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if await db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    rows = (
        await db.execute(
            select(ToolApprovalRequest)
            .where(ToolApprovalRequest.task_id == task_id)
            .order_by(ToolApprovalRequest.created_at)
        )
    ).scalars().all()
    return {"items": [ToolApprovalRead.model_validate(row) for row in rows]}


@task_router.post(
    "/{task_id}/tool-approvals/{approval_id}/resolve",
    response_model=ToolApprovalRead,
)
async def resolve_tool_approval(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    body: ToolApprovalResolve,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    approval = await db.get(ToolApprovalRequest, approval_id)
    if task is None or approval is None or approval.task_id != task_id:
        raise HTTPException(status_code=404, detail="Tool approval request not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Tool approval request is already resolved")

    if body.decision == "always_allow":
        rule = dict(approval.permission_rule or {})
        project_tools = (
            await db.execute(
                select(ToolBinding).where(
                    ToolBinding.project_id == task.project_id,
                )
            )
        ).scalars().all()
        existing = next((tool for tool in project_tools if tool.config == rule), None)
        if existing is None:
            db.add(
                ToolBinding(
                    project_id=task.project_id,
                    name=f"Allow {approval.tool_name} {str(approval.id)[:8]}",
                    config=rule,
                )
            )
        approval.status = "approved_project"
        approval.resolution_scope = "project"
        response_text = f"Permission approved for this project: {approval.tool_name}. Retry the tool call."
    elif body.decision == "approve_once":
        approval.status = "approved_once"
        approval.resolution_scope = "once"
        response_text = f"Permission approved once: {approval.tool_name}. Retry the tool call."
    else:
        approval.status = "denied"
        approval.resolution_scope = "once"
        response_text = f"Permission denied: {approval.tool_name}. Continue without this tool call."

    approval.resolved_at = datetime.now(timezone.utc)
    task.status = TaskStatus.queued
    db.add(
        Message(
            task_id=task_id,
            sender=MessageSender.user,
            content_text=response_text,
        )
    )
    await db.commit()
    await db.refresh(approval)
    await process_manager.resume_after_approval(task_id)
    return approval
