"""Pydantic schemas for ToolBinding."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ToolBindingCreate(BaseModel):
    name: str
    config: dict = Field(default_factory=dict)


class ToolBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    config: dict
    created_at: datetime
