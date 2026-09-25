from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import AgentBackend, RuntimeMode


class TaskInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    sequence: int
    backend: AgentBackend
    runtime_mode: RuntimeMode
    session_id: str | None
    model: str | None
    thinking_level: str | None
    status: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    started_at: datetime
    completed_at: datetime | None


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    task_id: uuid.UUID
    invocation_id: uuid.UUID | None
    kind: str
    title: str
    content: str | None
    event_metadata: dict
    created_at: datetime
