"""Pydantic schemas for Task."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AgentBackend, RuntimeMode, TaskStatus


class TaskTagsMixin(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            clean = " ".join(value.strip().split())
            if not clean:
                continue
            if len(clean) > 32:
                raise ValueError("Task tags must be 32 characters or fewer")
            if clean.lower() not in {item.lower() for item in normalized}:
                normalized.append(clean)
        return normalized


class TaskCreate(TaskTagsMixin):
    title: str
    initial_prompt: str
    backend: AgentBackend | None = None
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    agent_id: uuid.UUID | None = None
    context_strategy: str | None = None
    media: list = Field(default_factory=list)
    runtime_mode: RuntimeMode | None = None


class TaskModelUpdate(BaseModel):
    model: str


class TaskBackendUpdate(BaseModel):
    backend: AgentBackend


class TaskModelsUpdate(BaseModel):
    models: list[str]


class TaskThinkingUpdate(BaseModel):
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"]


class TaskContextStrategyUpdate(BaseModel):
    context_strategy: str


class TaskTagsUpdate(TaskTagsMixin):
    pass


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    initial_prompt: str
    status: TaskStatus
    attention_reason: str | None
    backend: AgentBackend
    runtime_mode: RuntimeMode
    model: str | None
    fallback_models: list[str]
    tags: list[str]
    thinking_level: str
    agent_id: uuid.UUID | None
    context_strategy: str
    session_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cron_job_id: uuid.UUID | None
