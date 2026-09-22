"""ProjectArtifact endpoints, nested under /projects/{id}/artifacts."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectArtifact
from app.db.session import get_db
from app.schemas.artifact import ProjectArtifactCreate, ProjectArtifactRead

router = APIRouter(prefix="/projects", tags=["artifacts"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/artifacts")
async def list_artifacts(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(
        select(ProjectArtifact).where(ProjectArtifact.project_id == project_id)
    )
    artifacts = result.scalars().all()
    return {"items": [ProjectArtifactRead.model_validate(a) for a in artifacts]}


@router.post("/{project_id}/artifacts", status_code=201, response_model=ProjectArtifactRead)
async def create_artifact(
    project_id: uuid.UUID, body: ProjectArtifactCreate, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    artifact = ProjectArtifact(project_id=project_id, **body.model_dump())
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    return artifact


@router.delete("/{project_id}/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(
    project_id: uuid.UUID, artifact_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    artifact = await db.get(ProjectArtifact, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.delete(artifact)
    await db.commit()
