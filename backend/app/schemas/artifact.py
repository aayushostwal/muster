"""Pydantic schemas for ProjectArtifact."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectArtifactCreate(BaseModel):
    name: str
    local_path: str
    remote_url: str | None = None


class ProjectArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    local_path: str
    remote_url: str | None
    created_at: datetime
