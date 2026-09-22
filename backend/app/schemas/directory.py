"""Pydantic schemas for DirectoryBinding."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import AccessScope


class DirectoryBindingCreate(BaseModel):
    path: str
    access_scope: AccessScope


class DirectoryBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    path: str
    access_scope: AccessScope
    created_at: datetime
