"""PR delivery endpoints, nested under /tasks/{id}/pr-delivery (see
docs/SPEC.md "PR delivery" and `app/services/pr_delivery.py`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Task
from app.db.session import get_db
from app.schemas.pr_delivery import (
    PrDeliveryCompleteWithoutPr,
    PrDeliveryConfirmRequest,
    PrDeliveryEligibility,
    PrDeliveryPrepareRequest,
    PrDeliveryRunRead,
)
from app.services import pr_delivery

router = APIRouter(prefix="/tasks", tags=["pr-delivery"])


async def _get_task_and_project(db: AsyncSession, task_id: uuid.UUID) -> tuple[Task, Project]:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    project = await db.get(Project, task.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return task, project


async def _get_run_or_404(db: AsyncSession, task_id: uuid.UUID, run_id: uuid.UUID):
    from app.db.models import PrDeliveryRun

    run = await db.get(PrDeliveryRun, run_id)
    if run is None or run.task_id != task_id:
        raise HTTPException(status_code=404, detail="PR delivery run not found")
    return run


@router.get("/{task_id}/pr-delivery/eligibility", response_model=PrDeliveryEligibility)
async def get_eligibility(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task, project = await _get_task_and_project(db, task_id)
    data = await pr_delivery.eligibility(db, task, project)
    active_run = await pr_delivery.get_active_run(db, task_id)
    active_run_read = PrDeliveryRunRead.model_validate(active_run) if active_run is not None else None
    return PrDeliveryEligibility(**data, active_run=active_run_read)


@router.get("/{task_id}/pr-delivery")
async def list_runs(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_and_project(db, task_id)
    runs = await pr_delivery.list_runs(db, task_id)
    return {"items": [PrDeliveryRunRead.model_validate(run) for run in runs]}


@router.post("/{task_id}/pr-delivery/prepare", status_code=201, response_model=PrDeliveryRunRead)
async def prepare_pr(
    task_id: uuid.UUID, body: PrDeliveryPrepareRequest, db: AsyncSession = Depends(get_db)
):
    task, project = await _get_task_and_project(db, task_id)
    try:
        run = await pr_delivery.prepare(
            db,
            task,
            project,
            base_branch=body.base_branch,
            remote_name=body.remote_name,
            draft=body.draft,
        )
    except pr_delivery.PrDeliveryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return run


@router.post("/{task_id}/pr-delivery/{run_id}/confirm", response_model=PrDeliveryRunRead)
async def confirm_pr(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    body: PrDeliveryConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    task, project = await _get_task_and_project(db, task_id)
    run = await _get_run_or_404(db, task_id, run_id)
    return await pr_delivery.confirm(
        db,
        task,
        project,
        run,
        commit_message=body.commit_message,
        pr_title=body.pr_title,
        pr_body=body.pr_body,
        draft=body.draft,
    )


@router.post("/{task_id}/pr-delivery/{run_id}/cancel", response_model=PrDeliveryRunRead)
async def cancel_pr(task_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_task_and_project(db, task_id)
    run = await _get_run_or_404(db, task_id, run_id)
    return await pr_delivery.cancel(db, run)


@router.post("/{task_id}/pr-delivery/{run_id}/sync", response_model=PrDeliveryRunRead)
async def sync_pr(task_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    _, project = await _get_task_and_project(db, task_id)
    run = await _get_run_or_404(db, task_id, run_id)
    return await pr_delivery.sync_status(db, project, run)


@router.post("/{task_id}/pr-delivery/complete-without-pr", response_model=PrDeliveryRunRead)
async def complete_without_pr(
    task_id: uuid.UUID, body: PrDeliveryCompleteWithoutPr, db: AsyncSession = Depends(get_db)
):
    task, project = await _get_task_and_project(db, task_id)
    return await pr_delivery.complete_without_pr(db, task, project, body.reason)
