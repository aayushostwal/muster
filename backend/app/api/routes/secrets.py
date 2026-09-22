"""Secret endpoints, nested under /projects/{id}/secrets. Values are never read back."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encrypt_secret
from app.db.models import Project, Secret
from app.db.session import get_db
from app.schemas.secret import SecretPut, SecretRead

router = APIRouter(prefix="/projects", tags=["secrets"])


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/secrets")
async def list_secrets(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    result = await db.execute(select(Secret).where(Secret.project_id == project_id))
    secrets = result.scalars().all()
    return {"items": [SecretRead.model_validate(s) for s in secrets]}


@router.put("/{project_id}/secrets/{key_name}", response_model=SecretRead)
async def upsert_secret(
    project_id: uuid.UUID, key_name: str, body: SecretPut, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    result = await db.execute(
        select(Secret).where(Secret.project_id == project_id, Secret.key_name == key_name)
    )
    secret = result.scalar_one_or_none()
    encrypted = encrypt_secret(body.value)
    if secret is None:
        secret = Secret(project_id=project_id, key_name=key_name, encrypted_value=encrypted)
        db.add(secret)
    else:
        secret.encrypted_value = encrypted
    await db.commit()
    await db.refresh(secret)
    return secret


@router.delete("/{project_id}/secrets/{key_name}", status_code=204)
async def delete_secret(
    project_id: uuid.UUID, key_name: str, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Secret).where(Secret.project_id == project_id, Secret.key_name == key_name)
    )
    secret = result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    await db.delete(secret)
    await db.commit()
