"""Pydantic schemas for Message."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import MessageSender


class MessageCreate(BaseModel):
    content_text: str | None = None
    media: list = Field(default_factory=list)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    sender: MessageSender
    content_text: str | None
    media: list
    is_blocking_question: bool
    created_at: datetime
