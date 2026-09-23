"""Pydantic schemas for Project."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import AgentBackend


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    default_backend: AgentBackend
    default_model: str | None = None
    default_context_strategy: str = "full"
    primary_directory_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_backend: AgentBackend | None = None
    default_model: str | None = None
    default_context_strategy: str | None = None
    primary_directory_id: uuid.UUID | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    default_backend: AgentBackend
    default_model: str | None
    default_context_strategy: str
    primary_directory_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
