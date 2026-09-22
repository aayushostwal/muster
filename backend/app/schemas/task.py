"""Pydantic schemas for Task."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentBackend, TaskStatus


class TaskCreate(BaseModel):
    title: str
    initial_prompt: str
    backend: AgentBackend | None = None
    model: str | None = None
    context_strategy: str | None = None
    media: list = Field(default_factory=list)


class TaskModelUpdate(BaseModel):
    model: str


class TaskContextStrategyUpdate(BaseModel):
    context_strategy: str


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    initial_prompt: str
    status: TaskStatus
    backend: AgentBackend
    model: str | None
    context_strategy: str
    session_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cron_job_id: uuid.UUID | None
