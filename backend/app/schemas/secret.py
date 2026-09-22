"""Pydantic schemas for Secret. The value is never exposed on read."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SecretPut(BaseModel):
    value: str


class SecretRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    key_name: str
    created_at: datetime
