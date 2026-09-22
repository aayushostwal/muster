"""Pydantic schemas for CronJob."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import AgentBackend


class CronJobCreate(BaseModel):
    name: str
    schedule_expr: str
    prompt: str
    backend: AgentBackend
    model: str | None = None


class CronJobUpdate(BaseModel):
    name: str | None = None
    schedule_expr: str | None = None
    prompt: str | None = None
    backend: AgentBackend | None = None
    model: str | None = None


class CronJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    schedule_expr: str
    prompt: str
    backend: AgentBackend
    model: str | None
    enabled: bool
    last_run_at: datetime | None
    last_status: str | None
    created_at: datetime
