"""Pydantic schemas for Task."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgentBackend, TaskStatus


class TaskCreate(BaseModel):
    title: str
    initial_prompt: str
    backend: AgentBackend | None = None
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    agent_id: uuid.UUID | None = None
    context_strategy: str | None = None
    media: list = Field(default_factory=list)


class TaskModelUpdate(BaseModel):
    model: str


class TaskModelsUpdate(BaseModel):
    models: list[str]


class TaskThinkingUpdate(BaseModel):
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"]


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
    fallback_models: list[str]
    thinking_level: str
    agent_id: uuid.UUID | None
    context_strategy: str
    session_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cron_job_id: uuid.UUID | None
