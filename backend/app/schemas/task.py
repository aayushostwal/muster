"""Pydantic schemas for Task."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import AgentBackend, RuntimeMode, TaskStatus


class TaskAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=2000)
    mime: str = Field(default="application/octet-stream", max_length=255)
    size: int = Field(ge=0, le=25 * 1024 * 1024)
    url: str = Field(min_length=1, max_length=2000)


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
    source_key: str | None = Field(default=None, min_length=1, max_length=300)
    related_source_key: str | None = Field(default=None, min_length=1, max_length=300)
    related_task_id: uuid.UUID | None = None
    source_event_key: str | None = Field(default=None, min_length=1, max_length=300)
    source_update: str | None = Field(default=None, min_length=1, max_length=12000)

    @field_validator("source_key", "related_source_key", "source_event_key", "source_update", mode="before")
    @classmethod
    def normalize_source_key(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_source_update(self):
        if (self.source_event_key is None) != (self.source_update is None):
            raise ValueError("Supply both source_event_key and source_update")
        if (self.related_source_key or self.related_task_id or self.source_event_key) and not self.source_key:
            raise ValueError("Source linking and updates require source_key")
        return self

    title: str
    initial_prompt: str
    backend: AgentBackend | None = None
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    agent_id: uuid.UUID | None = None
    context_strategy: str | None = None
    media: list[TaskAttachment] = Field(default_factory=list, max_length=10)
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
    source_key: str | None = None
    title: str
    initial_prompt: str
    media: list[TaskAttachment]
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
