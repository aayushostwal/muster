"""CronJob endpoints, nested under /projects/{id}/cron-jobs.

Every create/update/enable/disable/delete calls
`app.services.cron_scheduler.sync_jobs_from_db()` so the in-memory
APScheduler stays in sync with Postgres (see docs/SPEC.md #integration-seams).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CronJob, Project
from app.db.session import get_db
from app.schemas.cron import CronJobCreate, CronJobRead, CronJobUpdate
from app.services.cron_scheduler import _fire_cron_job, sync_jobs_from_db
from app.services.cron_scheduler import is_valid_cron

router = APIRouter(prefix="/projects", tags=["cron"])
global_router = APIRouter(tags=["cron"])


@global_router.get("/cron-jobs")
async def list_all_cron_jobs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CronJob).order_by(CronJob.created_at.desc()))).scalars().all()
    return {"items": [CronJobRead.model_validate(row) for row in rows]}


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_cron_job_or_404(
    db: AsyncSession, project_id: uuid.UUID, cron_id: uuid.UUID
) -> CronJob:
    cron_job = await db.get(CronJob, cron_id)
    if cron_job is None or cron_job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return cron_job


@router.get("/{project_id}/cron-jobs")
async def list_cron_jobs(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(select(CronJob).where(CronJob.project_id == project_id))
    jobs = result.scalars().all()
    return {"items": [CronJobRead.model_validate(j) for j in jobs]}


@router.post("/{project_id}/cron-jobs", status_code=201, response_model=CronJobRead)
async def create_cron_job(
    project_id: uuid.UUID, body: CronJobCreate, db: AsyncSession = Depends(get_db)
):
    project = await _get_project_or_404(db, project_id)
    if body.interval_minutes is not None and project.primary_directory_id is None:
        raise HTTPException(status_code=422, detail="Choose a primary directory for this project before scheduling an agent")
    if not body.prompt.strip() or not body.name.strip():
        raise HTTPException(status_code=422, detail="Enter a name and prompt")
    if body.interval_minutes is None and not is_valid_cron(body.schedule_expr):
        raise HTTPException(status_code=422, detail="Enter a valid schedule")
    cron_job = CronJob(project_id=project_id, **body.model_dump())
    db.add(cron_job)
    await db.commit()
    await db.refresh(cron_job)
    sync_jobs_from_db()
    return cron_job


@router.patch("/{project_id}/cron-jobs/{cron_id}", response_model=CronJobRead)
async def update_cron_job(
    project_id: uuid.UUID,
    cron_id: uuid.UUID,
    body: CronJobUpdate,
    db: AsyncSession = Depends(get_db),
):
    cron_job = await _get_cron_job_or_404(db, project_id, cron_id)
    if body.schedule_expr is not None and not is_valid_cron(body.schedule_expr):
        raise HTTPException(status_code=422, detail="Enter a valid schedule")
    if body.prompt is not None and not body.prompt.strip():
        raise HTTPException(status_code=422, detail="Enter a prompt")
    if "thinking_level" in body.model_fields_set and body.thinking_level is None:
        raise HTTPException(status_code=422, detail="Choose a thinking level")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cron_job, field, value)
    await db.commit()
    await db.refresh(cron_job)
    sync_jobs_from_db()
    return cron_job


@router.post("/{project_id}/cron-jobs/{cron_id}/enable", response_model=CronJobRead)
async def enable_cron_job(
    project_id: uuid.UUID, cron_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    cron_job = await _get_cron_job_or_404(db, project_id, cron_id)
    cron_job.enabled = True
    await db.commit()
    await db.refresh(cron_job)
    sync_jobs_from_db()
    return cron_job


@router.post("/{project_id}/cron-jobs/{cron_id}/disable", response_model=CronJobRead)
async def disable_cron_job(
    project_id: uuid.UUID, cron_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    cron_job = await _get_cron_job_or_404(db, project_id, cron_id)
    cron_job.enabled = False
    await db.commit()
    await db.refresh(cron_job)
    sync_jobs_from_db()
    return cron_job


@router.post("/{project_id}/cron-jobs/{cron_id}/run-now")
async def run_cron_job_now(
    project_id: uuid.UUID, cron_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    await _get_cron_job_or_404(db, project_id, cron_id)
    task_id = await _fire_cron_job(cron_id, allow_disabled=True)
    return {"task_id": task_id}


@router.delete("/{project_id}/cron-jobs/{cron_id}", status_code=204)
async def delete_cron_job(
    project_id: uuid.UUID, cron_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    cron_job = await _get_cron_job_or_404(db, project_id, cron_id)
    await db.delete(cron_job)
    await db.commit()
    sync_jobs_from_db()
