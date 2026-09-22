"""Pydantic schemas for ContextSnapshot."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContextSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    summary_text: str
    raw_transcript_path: str
    token_count: int | None
    created_at: datetime
