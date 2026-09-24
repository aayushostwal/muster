from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectTaskTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    color: str | None = Field(default=None, max_length=30)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ProjectTaskTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = Field(default=None, max_length=30)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None


class ProjectTaskTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    color: str | None
    created_at: datetime
    updated_at: datetime

