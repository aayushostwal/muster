"""Pydantic schemas for TaskRunAttempt."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import FailureClass


class TaskRunAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    attempt_number: int
    failure_class: FailureClass | None
    error_message: str | None
    backoff_seconds: int | None
    created_at: datetime
